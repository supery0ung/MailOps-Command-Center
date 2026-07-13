"""
Flask Web 应用 - Gmail 邮件管理界面
"""
import os
import sys
import json
import re
import ssl
import shlex
import subprocess
from flask import Flask, render_template, request, jsonify, Response

from gmail_wrapper import GmailClient
from classifier import EmailClassifier
from queue_manager import QueueManager
from lib.unsubscribe import attempt_unsubscribe


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # 支持中文


def run_ai_command(prompt, timeout):
    """Run an optional local, CLI-compatible AI command without user-specific paths."""
    command = shlex.split(os.getenv('MAILOPS_AI_COMMAND', 'claude'))
    return subprocess.run(
        [*command, '--print', '--model', os.getenv('MAILOPS_AI_MODEL', 'claude-haiku-4-5-20251001'), prompt],
        capture_output=True, text=True, timeout=timeout
    )

# 初始化组件
gmail_client = GmailClient()
classifier = EmailClassifier()
queue_manager = QueueManager()

import time as _time
import threading

# 标签磁盘缓存路径
LABELS_CACHE_FILE = '.claude/labels_cache.json'
LABELS_CACHE_TTL = 3600  # 1 小时
_labels_refresh_lock = threading.Lock()

# 分类变更日志路径
CORRECTIONS_LOG   = '.claude/classification_corrections.jsonl'
IMPORTANCE_LOG    = '.claude/importance_corrections.jsonl'
os.makedirs('.claude', exist_ok=True)


def _load_labels_cache():
    """从磁盘读取标签缓存（含邮件数量）"""
    if not os.path.exists(LABELS_CACHE_FILE):
        return None, 0
    try:
        with open(LABELS_CACHE_FILE, 'r') as f:
            data = json.load(f)
        return data.get('labels', []), data.get('ts', 0)
    except Exception:
        return None, 0


def _save_labels_cache(labels):
    """保存标签缓存到磁盘"""
    try:
        with open(LABELS_CACHE_FILE, 'w') as f:
            json.dump({'labels': labels, 'ts': _time.time()}, f, ensure_ascii=False)
    except Exception:
        pass


def _refresh_labels_cache_async():
    """后台刷新标签邮件数量并写磁盘缓存"""
    def _do():
        if not _labels_refresh_lock.acquire(blocking=False):
            return  # 已有刷新在进行
        try:
            all_labels = gmail_client.list_labels_with_counts()
            user_labels = [l for l in all_labels if l['type'] == 'user']
            user_labels.sort(key=lambda l: l['messages_total'], reverse=True)
            _save_labels_cache(user_labels)
        except Exception:
            pass
        finally:
            _labels_refresh_lock.release()
    threading.Thread(target=_do, daemon=True).start()


@app.route('/')
def index():
    """主界面"""
    return render_template('index.html')


@app.route('/api/labels', methods=['GET'])
def get_labels():
    """
    获取用户自定义 Gmail 标签（过滤系统标签，按邮件数量排序）

    策略：
    - 磁盘缓存有效（<1小时）→ 直接返回（快）
    - 磁盘缓存过期 → 返回基本标签（快），后台刷新邮件数量
    - 无缓存 → 返回基本标签（快），后台刷新邮件数量
    """
    try:
        cached_labels, cache_ts = _load_labels_cache()
        now = _time.time()

        if cached_labels is not None and (now - cache_ts) < LABELS_CACHE_TTL:
            # 缓存有效，直接返回
            return jsonify({"success": True, "labels": cached_labels, "from_cache": True})

        # 缓存过期或不存在：快速返回基本标签，后台异步刷新数量
        _refresh_labels_cache_async()

        if cached_labels is not None:
            # 返回旧缓存（数量可能不准但有）
            return jsonify({"success": True, "labels": cached_labels, "from_cache": True, "refreshing": True})

        # 首次启动无缓存：同步获取基本标签（无数量），按名称排序
        all_labels = gmail_client.list_labels()
        user_labels = [l for l in all_labels if l['type'] == 'user']
        user_labels.sort(key=lambda l: l['name'])
        return jsonify({"success": True, "labels": user_labels, "from_cache": False, "refreshing": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


USAGE_SNAPSHOT_FILE = '.claude/usage_snapshot.json'


@app.route('/api/usage-refresh', methods=['POST'])
def refresh_usage_from_cli():
    """从 JSONL 计算 Claude 用量（output tokens），使用正确的时间窗口"""
    try:
        import glob
        from datetime import datetime, timedelta, timezone

        LA = timezone(timedelta(hours=-7))   # PDT (UTC-7)
        UTC = timezone.utc
        now_utc = datetime.now(UTC)
        now_la  = now_utc.astimezone(LA)

        # ── 会话窗口：今天 3am PT ──
        session_start_la = now_la.replace(hour=3, minute=0, second=0, microsecond=0)
        if now_la < session_start_la:
            session_start_la -= timedelta(days=1)
        session_start_utc = session_start_la.astimezone(UTC).isoformat()

        # 下次重置
        next_session_reset_la = session_start_la + timedelta(days=1)
        session_reset_str = next_session_reset_la.strftime("resets %-I%p PT").lower()

        # ── 周窗口：从锚点向前推，找当前窗口起点 ──
        anchor = datetime.fromisoformat(_WEEK_RESET_ANCHOR_UTC)
        # 找最近一次 <= now 的重置点
        diff_secs = (now_utc - anchor).total_seconds()
        weeks_back = int(diff_secs // (7 * 86400))
        if diff_secs < 0:
            weeks_back -= 1
        week_start_utc = (anchor + timedelta(weeks=weeks_back)).isoformat()
        week_end_utc   = (anchor + timedelta(weeks=weeks_back + 1)).isoformat()
        next_reset_la  = (anchor + timedelta(weeks=weeks_back + 1)).astimezone(LA)
        week_reset_str = next_reset_la.strftime("resets %b %-d %-I%p PT").lower()

        # ── 读 JSONL ──
        session_out = 0
        week_out    = 0
        pattern = os.path.expanduser('~/.claude/projects/**/*.jsonl')
        for path in glob.glob(pattern, recursive=True):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        d  = json.loads(line)
                        ts = d.get('timestamp', '')
                        u  = d.get('message', {}).get('usage')
                        if not u or not ts:
                            continue
                        out = u.get('output_tokens', 0)
                        if ts >= session_start_utc:
                            session_out += out
                        if week_start_utc <= ts < week_end_utc:
                            week_out += out
            except Exception:
                pass

        limits = _get_usage_limits()
        sess_limit   = limits.get('session_output', limits.get('daily_output', 264_000))
        weekly_limit = limits.get('weekly_output', 875_000)

        session_pct = round(session_out / sess_limit   * 100) if sess_limit   else None
        week_pct    = round(week_out    / weekly_limit * 100) if weekly_limit else None

        snapshot = {
            "session_pct":   session_pct,
            "week_pct":      week_pct,
            "session_reset": session_reset_str,
            "week_reset":    week_reset_str,
            "updated_at":    now_utc.isoformat(),
        }
        with open(USAGE_SNAPSHOT_FILE, 'w') as f:
            json.dump(snapshot, f, ensure_ascii=False)
        return jsonify({"success": True, **snapshot})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/usage-snapshot', methods=['GET'])
def get_usage_snapshot():
    """读取最新的 /usage 快照（session % 和 week %）"""
    try:
        if os.path.exists(USAGE_SNAPSHOT_FILE):
            with open(USAGE_SNAPSHOT_FILE) as f:
                return jsonify({"success": True, **json.load(f)})
        return jsonify({"success": True, "session_pct": None, "week_pct": None})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/usage-snapshot', methods=['POST'])
def set_usage_snapshot():
    """保存 /usage 快照数据"""
    try:
        data = request.get_json()
        snapshot = {
            "session_pct":   data.get("session_pct"),
            "week_pct":      data.get("week_pct"),
            "session_reset": data.get("session_reset", ""),
            "week_reset":    data.get("week_reset", ""),
            "updated_at":    __import__('datetime').datetime.now().isoformat(),
        }
        with open(USAGE_SNAPSHOT_FILE, 'w') as f:
            json.dump(snapshot, f, ensure_ascii=False)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/usage-limits', methods=['POST'])
def set_usage_limits():
    """保存用户设置的 Claude 限额"""
    try:
        data = request.get_json()
        limits = _get_usage_limits()
        if 'daily_output' in data:
            limits['daily_output'] = int(data['daily_output'])
        if 'weekly_output' in data:
            limits['weekly_output'] = int(data['weekly_output'])
        with open(USAGE_LIMITS_FILE, 'w') as f:
            json.dump(limits, f)
        return jsonify({"success": True, "limits": limits})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/star/<email_id>', methods=['POST'])
def star_email(email_id):
    """给邮件加星标（同步到 Gmail）"""
    try:
        gmail_client.star_email(email_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/unstar/<email_id>', methods=['POST'])
def unstar_email(email_id):
    """取消邮件星标"""
    try:
        gmail_client.unstar_email(email_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/log-importance', methods=['POST'])
def log_importance():
    """记录用户手动更改重要性标记"""
    try:
        data = request.get_json()
        entry = {
            "timestamp":    __import__('datetime').datetime.now().isoformat(),
            "email_id":     data.get("email_id"),
            "subject":      data.get("subject", ""),
            "sender":       data.get("sender", ""),
            "sender_email": data.get("sender_email", ""),
            "label":        data.get("label", ""),
            "original":     data.get("original"),   # True/False
            "new_value":    data.get("new_value"),  # True/False
        }
        with open(IMPORTANCE_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/log-correction', methods=['POST'])
def log_correction():
    """
    记录用户手动更改分类

    Body:
        {
            "email_id": "...",
            "subject": "...",
            "sender": "...",
            "original_label": "inbox",
            "new_label": "Finance"
        }
    """
    try:
        data = request.get_json()
        entry = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "email_id": data.get("email_id"),
            "subject": data.get("subject", ""),
            "sender": data.get("sender", ""),
            "original_label": data.get("original_label"),
            "new_label": data.get("new_label"),
        }
        with open(CORRECTIONS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/update-rules', methods=['POST'])
def update_rules():
    """根据纠错日志用 Claude 更新 classifier.py 中的分类规则"""

    # 读取纠错日志
    corrections = []
    if os.path.exists(CORRECTIONS_LOG):
        with open(CORRECTIONS_LOG, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    corrections.append(json.loads(line))

    importance_corrections = []
    if os.path.exists(IMPORTANCE_LOG):
        with open(IMPORTANCE_LOG, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    importance_corrections.append(json.loads(line))

    if not corrections and not importance_corrections:
        return jsonify({"success": False, "error": "没有纠错记录，无需更新规则"})

    # 读取当前 classifier.py
    classifier_path = os.path.join(os.path.dirname(__file__), 'classifier.py')
    with open(classifier_path, encoding='utf-8') as f:
        current_code = f.read()

    # 构建 prompt
    correction_lines = "\n".join([
        f"- [{c['timestamp'][:10]}] 发件人: {c['sender']} | 主题: {c['subject']} | {c['original_label']} → {c['new_label']}"
        for c in corrections[-50:]  # 最近50条
    ]) or "（无）"

    importance_lines = "\n".join([
        f"- [{c['timestamp'][:10]}] 发件人: {c['sender']} | 主题: {c['subject']} | 重要性: {c['original']} → {c['new_value']}"
        for c in importance_corrections[-30:]
    ]) or "（无）"

    prompt = f"""You are updating an email classifier's Python rules based on user corrections.

USER CORRECTIONS (emails where user changed the classification):
{correction_lines}

USER IMPORTANCE CORRECTIONS (emails where user changed importance flag):
{importance_lines}

CURRENT classifier.py:
```python
{current_code}
```

Analyze the correction patterns. If a sender or subject pattern appears multiple times being corrected to the same label, add it to the appropriate rule method. If something is repeatedly moved to archive, add it to _should_archive. If something is kept in inbox, add it to _should_keep_in_inbox. Only add patterns that are clearly repeated or obvious.

Return ONLY the complete updated classifier.py content with no other text, no markdown code fences."""

    result = run_ai_command(prompt, timeout=120)

    if result.returncode != 0:
        return jsonify({"success": False, "error": result.stderr[:300]}), 500

    response_text = result.stdout.strip()

    # 去掉可能的 markdown 代码块
    match = re.search(r'```(?:python)?\s*([\s\S]*?)```', response_text)
    if match:
        response_text = match.group(1).strip()

    # 验证是合法 Python（包含 class EmailClassifier）
    if 'class EmailClassifier' not in response_text:
        return jsonify({"success": False, "error": "Claude 返回内容格式不对，未更新文件"}), 500

    # 写回文件
    with open(classifier_path, 'w', encoding='utf-8') as f:
        f.write(response_text)

    # 重新加载分类器
    import importlib
    import classifier as classifier_module
    importlib.reload(classifier_module)
    from classifier import EmailClassifier as UpdatedClassifier
    app.config['classifier'] = UpdatedClassifier()

    return jsonify({
        "success": True,
        "message": f"规则已更新（基于 {len(corrections)} 条分类纠错 + {len(importance_corrections)} 条重要性纠错）"
    })


@app.route('/api/fetch', methods=['POST'])
def fetch_emails():
    """
    获取邮件并自动分类

    Body:
        {
            "max_emails": 50,
            "include_read": false
        }

    Returns:
        [
            {
                "email": {...},
                "classification": {
                    "label": "Finance",
                    "confidence": "high",
                    "reason": "Matches a portable finance rule.",
                    "needs_claude": false
                }
            }
        ]
    """
    try:
        data = request.get_json() or {}
        max_emails = data.get('max_emails', 50)
        include_read = data.get('include_read', True)

        # 构建查询
        query = "in:inbox"
        if not include_read:
            query += " is:unread"

        # 获取邮件
        emails = gmail_client.fetch_emails(query=query, max_results=max_emails)

        # 自动分类（STARRED 邮件直接保留 inbox，跳过规则和 Claude）
        results = []
        for email in emails:
            if 'STARRED' in email.get('labels', []):
                results.append({
                    "email": email,
                    "classification": {
                        "label": "inbox",
                        "confidence": "high",
                        "reason": "已加星标，保留在 Inbox",
                        "needs_claude": False,
                        "is_important": True,
                        "starred": True,
                    }
                })
            else:
                classification = classifier.classify(email)
                classification["is_important"] = classifier.is_important(email, classification["label"])
                classification["starred"] = False
                results.append({"email": email, "classification": classification})

        return jsonify({
            "success": True,
            "total": len(results),
            "emails": results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        # SSL errors are transient; reinitialize the client and retry once
        if 'SSL' in str(e) or 'ssl' in type(e).__name__.lower():
            try:
                gmail_client.__init__()
                emails = gmail_client.fetch_emails(query=query, max_results=max_emails)
                results = []
                for email in emails:
                    if 'STARRED' in email.get('labels', []):
                        results.append({
                            "email": email,
                            "classification": {
                                "label": "inbox",
                                "confidence": "high",
                                "reason": "已加星标，保留在 Inbox",
                                "needs_claude": False,
                                "is_important": True,
                                "starred": True,
                            }
                        })
                    else:
                        classification = classifier.classify(email)
                        classification["is_important"] = classifier.is_important(email, classification["label"])
                        classification["starred"] = False
                        results.append({"email": email, "classification": classification})
                return jsonify({"success": True, "total": len(results), "emails": results})
            except Exception as retry_e:
                traceback.print_exc()
                return jsonify({"success": False, "error": str(retry_e)}), 500
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/email/<email_id>', methods=['GET'])
def get_email_detail(email_id):
    """获取邮件完整内容"""
    try:
        email = gmail_client.get_email(email_id)
        return jsonify({
            "success": True,
            "email": email
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/email/<email_id>/attachment/<attachment_id>/save', methods=['POST'])
def save_attachment(email_id, attachment_id):
    """将附件保存到本地文件系统"""
    import base64, os
    data = request.get_json() or {}
    filename = data.get('filename', 'attachment')
    mime = data.get('mimeType', 'application/octet-stream')
    save_dir = data.get('save_dir', os.path.expanduser('~/Downloads'))
    try:
        att = gmail_client.get_attachment(email_id, attachment_id)
        binary = base64.urlsafe_b64decode(att['data'] + '==')
        save_dir = os.path.expanduser(save_dir)
        os.makedirs(save_dir, exist_ok=True)
        # 避免文件名冲突
        dest = os.path.join(save_dir, filename)
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(save_dir, f'{base}_{counter}{ext}')
            counter += 1
        with open(dest, 'wb') as f:
            f.write(binary)
        return jsonify({"success": True, "path": dest})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


USAGE_LIMITS_FILE = '.claude/usage_limits.json'
DEFAULT_LIMITS = {
    # Based on back-calculation from /usage output (output tokens only)
    "session_output": 264_000,   # session resets 3am PT daily
    "weekly_output":  875_000,   # week resets every ~7 days
    # Legacy keys kept for compatibility
    "daily_output":   264_000,
}

# Week reset anchor: Apr 7 2026 11pm PT = Apr 8 06:00 UTC
# Claude Code resets weekly at this interval
_WEEK_RESET_ANCHOR_UTC = "2026-04-08T06:00:00+00:00"

def _get_usage_limits():
    try:
        if os.path.exists(USAGE_LIMITS_FILE):
            with open(USAGE_LIMITS_FILE) as f:
                return {**DEFAULT_LIMITS, **json.load(f)}
    except Exception:
        pass
    return DEFAULT_LIMITS


@app.route('/api/usage', methods=['GET'])
def get_usage():
    """读取 ~/.claude JSONL，统计今日和本周 Claude token 用量"""
    try:
        import glob
        from datetime import datetime, timedelta

        today_dt = datetime.now().date()
        today_str = str(today_dt)
        # 本周一到今天
        week_start = today_dt - timedelta(days=today_dt.weekday())
        week_days = {str(week_start + timedelta(days=i)) for i in range(7)}

        today = {'input': 0, 'output': 0, 'cache_read': 0}
        week  = {'input': 0, 'output': 0, 'cache_read': 0}
        # 每天的 output，供迷你图用
        daily = {str(week_start + timedelta(days=i)): 0 for i in range(7)}

        pattern = os.path.expanduser('~/.claude/projects/**/*.jsonl')
        for path in glob.glob(pattern, recursive=True):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        d = json.loads(line)
                        ts  = d.get('timestamp', '')[:10]
                        u   = d.get('message', {}).get('usage')
                        if not u:
                            continue
                        out = u.get('output_tokens', 0)
                        inp = u.get('input_tokens', 0)
                        cr  = u.get('cache_read_input_tokens', 0)
                        if ts == today_str:
                            today['output'] += out
                            today['input']  += inp
                            today['cache_read'] += cr
                        if ts in week_days:
                            week['output'] += out
                            week['input']  += inp
                            week['cache_read'] += cr
                        if ts in daily:
                            daily[ts] += out
            except Exception:
                pass

        limits = _get_usage_limits()
        return jsonify({
            "success": True,
            "today":  today,
            "week":   week,
            "daily":  daily,          # {"2026-04-01": 12345, ...}
            "limits": limits,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/translate', methods=['POST'])
def translate_email():
    """
    用 Google Translate 翻译邮件正文
    Body: {"text": "...", "html": "...（可选）"}
    - 有 html 时：把翻译注入 HTML，返回 {"success": true, "html": "..."}
    - 无 html 时：逐段返回 {"success": true, "paragraphs": [{en, zh}]}
    """
    import re
    from deep_translator import GoogleTranslator
    from bs4 import BeautifulSoup

    try:
        body = request.get_json() or {}
        text = (body.get('text') or '').strip()
        html = (body.get('html') or '').strip()
        if not text and not html:
            return jsonify({"success": False, "error": "no text"}), 400

        translator = GoogleTranslator(source='auto', target='zh-CN')

        if html:
            # 解析 HTML，在每个有实质内容的 <p>/<td>/<li> 后注入中文翻译
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup.find_all(['p', 'li', 'td', 'h1', 'h2', 'h3']):
                txt = tag.get_text(separator=' ', strip=True)
                if len(txt) < 25 or txt.startswith('http'):
                    continue
                try:
                    zh = translator.translate(txt[:2000])
                except Exception:
                    continue
                if not zh or zh == txt:
                    continue
                zh_tag = soup.new_tag('div')
                zh_tag['style'] = (
                    'font-size:1em;line-height:1.5;'
                    'margin:2px 0 10px;'
                    'border-left:3px solid #4a90e2;padding-left:8px;opacity:0.85;'
                )
                zh_tag.string = zh
                tag.insert_after(zh_tag)
            return jsonify({"success": True, "html": str(soup)})

        else:
            # 纯文本：按段落翻译
            paras = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 20]
            if not paras:
                paras = [s.strip() for s in text.split('\n') if len(s.strip()) > 20]
            result = []
            for para in paras[:40]:
                try:
                    zh = translator.translate(para[:2000])
                except Exception:
                    zh = ''
                if zh:
                    result.append({"en": para, "zh": zh})
            if not result:
                return jsonify({"success": False, "error": "无可翻译内容"}), 500
            return jsonify({"success": True, "paragraphs": result})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/claude-classify', methods=['POST'])
def claude_classify():
    """
    用 Claude API 直接分类邮件

    Body:
        {
            "emails": [{"id": "...", "sender": "...", "subject": "...", "snippet": "..."}]
        }

    Returns:
        {
            "success": true,
            "classifications": [{"email_id": "...", "label": "Finance", "reason": "..."}]
        }
    """
    try:
        data = request.get_json()
        emails = data.get('emails', [])

        if not emails:
            return jsonify({"success": False, "error": "No emails provided"}), 400

        email_list = "\n\n".join([
            f"Email {i+1}:\nID: {e['id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nSnippet: {e.get('snippet', '')}"
            for i, e in enumerate(emails)
        ])

        prompt = f"""Classify these emails. Available labels:
- Finance: invoices, receipts, payments, statements, and transactions
- Operations: projects, meetings, contracts, and support requests
- People & Education: training, school, student, and people-related mail
- Travel: flights, hotels, reservations, and itineraries
- Technology: software, APIs, deployments, and security alerts
- archive: Not important, can be archived
- inbox: Keep in inbox, needs attention

{email_list}

Respond with ONLY a JSON array, no other text:
[{{"email_id": "id1", "label": "Finance", "reason": "brief reason"}}, ...]"""

        # Uses the local command configured in MAILOPS_AI_COMMAND.
        result = run_ai_command(prompt, timeout=60)
        if result.returncode != 0:
            return jsonify({"success": False, "error": result.stderr[:200]}), 500

        response_text = result.stdout.strip()
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text)
        if match:
            response_text = match.group(1).strip()

        classifications = json.loads(response_text)

        return jsonify({
            "success": True,
            "classifications": classifications
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/classify-complex', methods=['POST'])
def classify_complex():
    """
    将邮件加入 Claude 审核队列

    Body:
        {
            "email_ids": ["id1", "id2"]
        }

    Returns:
        {
            "success": true,
            "queue_id": "uuid"
        }
    """
    try:
        data = request.get_json()
        email_ids = data.get('email_ids', [])

        if not email_ids:
            return jsonify({
                "success": False,
                "error": "No email IDs provided"
            }), 400

        # 获取邮件详情
        emails = []
        for email_id in email_ids:
            email = gmail_client.get_email(email_id)
            emails.append({
                "id": email["id"],
                "subject": email["subject"],
                "sender": email["sender"],
                "snippet": email.get("snippet", "")
            })

        # 添加到队列
        queue_id = queue_manager.add_to_queue(emails)

        return jsonify({
            "success": True,
            "queue_id": queue_id,
            "count": len(emails)
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/classification-status/<queue_id>', methods=['GET'])
def get_classification_status(queue_id):
    """
    轮询队列状态

    Returns:
        {
            "status": "pending" | "completed",
            "results": [...]  # 如果已完成
        }
    """
    try:
        result = queue_manager.get_result(queue_id)

        if result is None:
            return jsonify({
                "status": "pending"
            })
        else:
            return jsonify({
                "status": "completed",
                "results": result["classifications"]
            })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/unsubscribe/<email_id>', methods=['POST'])
def unsubscribe_email(email_id):
    """退订邮件列表（解析 List-Unsubscribe 头并执行）"""
    try:
        result = attempt_unsubscribe(gmail_client.service, email_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/execute', methods=['POST'])
def execute_classification():
    """
    批量执行分类操作

    Body:
        [
            {"email_id": "...", "action": "move", "label": "Finance"},
            {"email_id": "...", "action": "archive"}
        ]

    Returns:
        {
            "success": true,
            "results": [...]
        }
    """
    try:
        actions = request.get_json()

        if not actions:
            return jsonify({
                "success": False,
                "error": "No actions provided"
            }), 400

        # 构建批量操作列表（每个 move 前自动添加 mark-read）
        batch_actions = []
        for action in actions:
            email_id = action["email_id"]

            # 先标记已读
            batch_actions.append({
                "action": "mark-read",
                "email_id": email_id
            })

            # 然后执行主操作
            if action["action"] == "move":
                batch_actions.append({
                    "action": "move",
                    "email_id": email_id,
                    "label_name": action["label"]
                })
            elif action["action"] == "archive":
                batch_actions.append({
                    "action": "archive",
                    "email_id": email_id
                })

        # 执行批量操作
        results = gmail_client.batch_execute(batch_actions)

        failures = [r for r in results if r and not r.get('success', True)]
        non_inbox = [a for a in actions if a['action'] != 'mark-read']
        archived = sum(1 for a in actions if a['action'] == 'archive')
        moved = sum(1 for a in actions if a['action'] == 'move')
        kept = sum(1 for a in actions if a['action'] == 'mark-read')

        return jsonify({
            "success": True,
            "processed": len(actions),
            "archived": archived,
            "moved": moved,
            "kept_in_inbox": kept,
            "failures": len(failures),
            "failure_details": [f.get('error', '') for f in failures[:5]],
            "results": results
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    print("=== Gmail 邮件管理 Web 界面 ===")
    print("访问: http://localhost:5001")
    print("按 Ctrl+C 停止服务器")
    print()
    app.run(debug=True, port=5001, host='127.0.0.1')
