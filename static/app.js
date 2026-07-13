// 全局变量
let allLabels = [];
let currentEmails = [];
let loadedEmailBodies = {};  // 缓存已加载的邮件正文

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    loadLabels();
    loadUsage();
    initTheme();
});

// 加载 Gmail 标签
async function loadLabels() {
    try {
        const response = await fetch('/api/labels');
        const data = await response.json();

        if (data.success) {
            allLabels = data.labels;
        } else {
            showNotification('加载标签失败: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Error loading labels:', error);
        showNotification('加载标签失败', 'error');
    }
}

// 获取邮件（并自动触发 Claude 分类）
async function fetchEmails() {
    const maxEmails = parseInt(document.getElementById('email-count').value);
    const fetchBtn = document.getElementById('fetch-btn');

    fetchBtn.disabled = true;
    showLoading('正在获取邮件...');
    updateStatus('正在获取邮件...');

    try {
        const response = await fetch('/api/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_emails: maxEmails, include_read: true })
        });

        const data = await response.json();
        hideLoading();

        if (data.success) {
            currentEmails = data.emails;
            renderEmailTable(data.emails);
            updateStatus(`已加载 ${data.total} 封邮件，正在 Claude 审核...`);
            document.getElementById('execute-btn').disabled = false;

            // 自动对所有邮件触发 Claude 审核
            autoClaudeClassify(data.emails, data.total);
        } else {
            showNotification('获取邮件失败: ' + data.error, 'error');
        }
    } catch (error) {
        hideLoading();
        console.error('Error fetching emails:', error);
        showNotification('获取邮件失败', 'error');
    } finally {
        fetchBtn.disabled = false;
    }
}

// 自动 Claude 分类（只处理规则不确定的邮件）
async function autoClaudeClassify(emailItems, total) {
    const emails = emailItems
        .filter(item => !item.classification.starred && item.classification.needs_claude)  // 只发不确定的
        .map(item => ({
            id: item.email.id,
            sender: item.email.sender,
            subject: item.email.subject,
            snippet: item.email.snippet || ''
        }));

    try {
        const response = await fetch('/api/claude-classify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ emails })
        });

        const data = await response.json();

        if (data.success) {
            updateTableWithClaudeResults(data.classifications);
            const claudeCount = emails.length;
            updateStatus(`已加载 ${total} 封邮件（${total - claudeCount} 规则分类，${claudeCount} 经 Claude 确认）`);
        } else {
            console.error('Claude classify error:', data.error);
            updateStatus(`已加载 ${total} 封邮件（规则分类）`);
        }
    } catch (error) {
        console.error('Error calling Claude classify:', error);
        updateStatus(`已加载 ${total} 封邮件（规则分类）`);
    }
}

// 渲染邮件表格
function renderEmailTable(emails) {
    const tbody = document.getElementById('email-tbody');
    tbody.innerHTML = '';

    if (emails.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-message">没有邮件</td></tr>';
        return;
    }

    emails.forEach((item, index) => {
        const email = item.email;
        const classification = item.classification;

        const isImportant = classification.is_important || false;

        // 主数据行
        const row = document.createElement('tr');
        row.dataset.emailId = email.id;
        row.dataset.index = index;
        row.classList.add('email-row');
        if (isImportant) row.classList.add('row-important');

        // 退订 checkbox（最左列）
        const unsubCell = document.createElement('td');
        unsubCell.style.textAlign = 'center';
        if (email.has_unsubscribe) {
            const unsubChk = document.createElement('input');
            unsubChk.type = 'checkbox';
            unsubChk.title = '勾选退订此邮件列表';
            unsubChk.addEventListener('change', () => {
                if (unsubChk.checked) unsubscribeEmail(email.id, unsubChk);
            });
            unsubCell.appendChild(unsubChk);
        }
        row.appendChild(unsubCell);

        // 勾选框
        const checkCell = document.createElement('td');
        checkCell.innerHTML = `<input type="checkbox" class="email-checkbox" onchange="updateButtonStates()">`;
        row.appendChild(checkCell);

        // 重要性 toggle
        const impCell = document.createElement('td');
        impCell.classList.add('importance-cell');
        const starBtn = document.createElement('button');
        starBtn.classList.add('star-btn');
        starBtn.textContent = isImportant ? '★' : '☆';
        starBtn.dataset.important = isImportant ? '1' : '0';
        starBtn.title = isImportant ? '重要（点击取消）' : '不重要（点击标记）';
        starBtn.addEventListener('click', () => toggleImportance(starBtn, row, email));
        impCell.appendChild(starBtn);
        row.appendChild(impCell);

        // 分类下拉框（左边第一列）
        const labelCell = document.createElement('td');
        const select = createLabelSelect(classification.label);
        select.classList.add('label-select');
        select.dataset.emailId = email.id;
        select.dataset.originalLabel = classification.label;
        if (classification.needs_claude) {
            select.classList.add('pending-claude');
        }
        // 记录用户手动更改
        select.addEventListener('change', () => {
            const original = select.dataset.originalLabel;
            const newVal = select.value;
            if (original !== newVal) {
                logCorrection(email.id, email.subject, email.sender, original, newVal);
                select.dataset.originalLabel = newVal;  // 更新基准，避免重复记录
            }
        });
        labelCell.appendChild(select);
        row.appendChild(labelCell);

        // 发件人 + 时间
        const senderCell = document.createElement('td');
        const senderName = email.sender.split('<')[0].trim() || email.sender_email;
        senderCell.innerHTML = `
            <div class="sender-name">${escapeHtml(senderName)}</div>
            <div class="sender-email">${escapeHtml(email.sender_email)}</div>
            <div class="email-date">${formatEmailDate(email.date)}</div>
        `;
        row.appendChild(senderCell);

        // 主题 + snippet 折叠展开
        const subjectCell = document.createElement('td');
        subjectCell.innerHTML = `
            <div class="subject">${escapeHtml(email.subject)}</div>
            <div class="snippet-line">
                <span class="snippet-text">${escapeHtml(email.snippet || '')}</span>
                <button class="expand-btn" onclick="toggleEmailBody('${email.id}', this)">▼ 展开</button>
            </div>
        `;
        row.appendChild(subjectCell);

        tbody.appendChild(row);

        // 邮件正文展开行（默认隐藏）
        const detailRow = document.createElement('tr');
        detailRow.id = `detail-${email.id}`;
        detailRow.classList.add('email-detail-row');
        detailRow.style.display = 'none';
        detailRow.innerHTML = `<td colspan="6"><div class="email-body-content" id="body-${email.id}">正在加载...</div></td>`;
        tbody.appendChild(detailRow);
    });
}

// 展开/收起邮件正文
async function toggleEmailBody(emailId, btn) {
    const detailRow = document.getElementById(`detail-${emailId}`);
    const bodyDiv = document.getElementById(`body-${emailId}`);

    if (detailRow.style.display === 'none') {
        // 展开
        detailRow.style.display = 'table-row';
        btn.textContent = '▲ 收起';

        // 如果还没加载过（或上次失败），从 API 获取
        if (!loadedEmailBodies[emailId]) {
            bodyDiv.innerHTML = '<div style="padding:8px;color:#666">加载中...</div>';
            try {
                const response = await fetch(`/api/email/${emailId}`);
                const data = await response.json();
                if (data.success) {
                    loadedEmailBodies[emailId] = {
                        html: data.email.body_html || null,
                        text: data.email.body_text || data.email.snippet || '(无正文)',
                        attachments: data.email.attachments || [],
                    };
                } else {
                    // 不缓存失败结果，下次展开可以重试
                    bodyDiv.innerHTML = `<div style="padding:8px;color:#c00">加载失败: ${escapeHtml(data.error || '')}</div>`;
                    return;
                }
            } catch (e) {
                // 不缓存失败结果，下次展开可以重试
                bodyDiv.innerHTML = `<div style="padding:8px;color:#c00">加载失败: ${escapeHtml(e.message || '网络错误')}</div>`;
                return;
            }
        }

        const cached = loadedEmailBodies[emailId];
        bodyDiv.innerHTML = '';

        // 附件列表
        if (cached.attachments && cached.attachments.length > 0) {
            const attBar = document.createElement('div');
            attBar.style.cssText = 'padding:8px 16px;display:flex;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--border);';
            cached.attachments.forEach(att => {
                const isImage = att.mimeType.startsWith('image/');
                const sizeKB = att.size ? ` (${Math.round(att.size/1024)}KB)` : '';
                const chip = document.createElement('button');
                chip.textContent = (isImage ? '⬇ ' : '📎 ') + att.filename + sizeKB;
                chip.style.cssText = 'font-size:12px;padding:3px 10px;background:var(--bg-secondary,#f0f0f0);border-radius:12px;color:var(--text-primary);border:1px solid var(--border);cursor:pointer;';
                chip.title = isImage ? '保存到 Downloads/Photos/School' : '保存到 Downloads';
                chip.addEventListener('click', () => saveAttachment(emailId, att, chip));
                attBar.appendChild(chip);
            });
            bodyDiv.appendChild(attBar);
        }

        // 翻译按钮（有正文才显示）
        if (cached.text && cached.text.length > 100) {
            const translateBtn = document.createElement('button');
            translateBtn.className = 'expand-btn translate-btn';
            translateBtn.textContent = '🔤 翻译成中文';
            translateBtn.style.margin = '8px 0 8px 16px';
            translateBtn.onclick = () => translateEmailBody(emailId, cached, translateBtn);
            bodyDiv.appendChild(translateBtn);
        }

        const contentDiv = document.createElement('div');
        contentDiv.id = `body-content-${emailId}`;
        bodyDiv.appendChild(contentDiv);

        if (cached.html) {
            // 用 iframe 沙箱渲染 HTML（自动显示图片和格式）
            const iframe = document.createElement('iframe');
            iframe.sandbox = 'allow-same-origin allow-popups';
            iframe.style.width = '100%';
            iframe.style.border = 'none';
            iframe.style.minHeight = '200px';
            contentDiv.appendChild(iframe);
            // 注入 <base target="_blank"> 让所有链接在新 tab 打开
            const htmlWithBase = cached.html.replace(
                /(<head[^>]*>)/i,
                '$1<base target="_blank" rel="noopener">'
            ) || '<base target="_blank" rel="noopener">' + cached.html;
            iframe.contentDocument.open();
            iframe.contentDocument.write(htmlWithBase);
            iframe.contentDocument.close();
            // 自动调整高度
            setTimeout(() => {
                iframe.style.height = iframe.contentDocument.body.scrollHeight + 'px';
            }, 100);
        } else {
            contentDiv.style.whiteSpace = 'pre-wrap';
            contentDiv.style.padding = '16px 20px';
            contentDiv.textContent = cached.text;
        }
    } else {
        // 收起
        detailRow.style.display = 'none';
        btn.textContent = '▼ 展开';
    }
}

// 翻译邮件正文，直接注入原邮件
async function translateEmailBody(emailId, cached, btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 翻译中...';
    try {
        const body = { text: cached.text || '' };
        if (cached.html) body.html = cached.html;

        const res = await fetch('/api/translate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!data.success) {
            btn.textContent = '翻译失败: ' + data.error;
            btn.disabled = false;
            return;
        }

        const contentDiv = document.getElementById(`body-content-${emailId}`);

        if (data.html) {
            // HTML 邮件：重新渲染带翻译的 HTML
            contentDiv.innerHTML = '';
            const iframe = document.createElement('iframe');
            iframe.sandbox = 'allow-same-origin allow-popups';
            iframe.style.cssText = 'width:100%;border:none;min-height:200px;';
            contentDiv.appendChild(iframe);
            const htmlWithBase = data.html.replace(
                /(<head[^>]*>)/i,
                '$1<base target="_blank" rel="noopener">'
            ) || '<base target="_blank" rel="noopener">' + data.html;
            iframe.contentDocument.open();
            iframe.contentDocument.write(htmlWithBase);
            iframe.contentDocument.close();
            setTimeout(() => {
                iframe.style.height = iframe.contentDocument.body.scrollHeight + 'px';
            }, 150);
        } else {
            // 纯文本：原文 + 中文紧跟其后，无边框
            contentDiv.innerHTML = '';
            contentDiv.style.padding = '0 20px 16px';
            data.paragraphs.forEach(({ en, zh }) => {
                const enP = document.createElement('p');
                enP.style.cssText = 'margin:0 0 3px;color:var(--text-primary);font-size:13px;line-height:1.7;white-space:pre-wrap;';
                enP.textContent = en;

                const zhP = document.createElement('p');
                zhP.style.cssText = 'margin:0 0 14px;color:var(--text-primary);font-size:13px;line-height:1.7;white-space:pre-wrap;border-left:3px solid var(--accent,#4a90e2);padding-left:8px;opacity:0.85;';
                zhP.textContent = zh;

                contentDiv.appendChild(enP);
                contentDiv.appendChild(zhP);
            });
        }

        btn.textContent = '✓ 已翻译';
        btn.style.color = 'var(--accent)';
    } catch (e) {
        btn.textContent = '翻译失败';
        btn.disabled = false;
    }
}

// 创建标签下拉框（支持多层标签）
function createLabelSelect(selectedLabel) {
    const select = document.createElement('select');

    // 固定操作：始终排最前
    const inboxOption = document.createElement('option');
    inboxOption.value = 'inbox';
    inboxOption.textContent = '📥 保留在 Inbox';
    if (selectedLabel === 'inbox') inboxOption.selected = true;
    select.appendChild(inboxOption);

    const archiveOption = document.createElement('option');
    archiveOption.value = 'archive';
    archiveOption.textContent = '📦 归档';
    if (selectedLabel === 'archive') archiveOption.selected = true;
    select.appendChild(archiveOption);

    const divider = document.createElement('option');
    divider.disabled = true;
    divider.textContent = '──────────';
    select.appendChild(divider);

    // 构建多层树结构
    // allLabels 已按 messages_total 降序排好
    // 用 optgroup 表示顶层父节点，option 缩进表示子节点
    const topLevel = [];   // [{label, children: [...]}]
    const labelMap = {};   // name -> node

    allLabels.forEach(label => {
        const parts = label.name.split('/');
        labelMap[label.name] = { label, children: [] };
        if (parts.length === 1) {
            topLevel.push(labelMap[label.name]);
        }
    });

    // 把子标签挂到父节点
    allLabels.forEach(label => {
        const parts = label.name.split('/');
        if (parts.length > 1) {
            const parentName = parts.slice(0, -1).join('/');
            if (labelMap[parentName]) {
                labelMap[parentName].children.push(labelMap[label.name]);
            } else {
                // 父节点不存在时作为顶层显示
                topLevel.push(labelMap[label.name]);
            }
        }
    });

    // 递归渲染节点到 select
    function renderNode(node, depth, container) {
        const label = node.label;
        const parts = label.name.split('/');
        const displayName = parts[parts.length - 1];  // 只显示最后一段
        const count = label.messages_total > 0 ? ` (${label.messages_total})` : '';
        const indent = '\u00A0\u00A0'.repeat(depth);

        if (node.children.length > 0 && depth === 0) {
            // 有子节点的顶层：父标签先作为普通 option，再建 optgroup 放子标签
            const parentOpt = document.createElement('option');
            parentOpt.value = label.id;
            parentOpt.textContent = displayName + count;
            if (selectedLabel === label.id || selectedLabel === label.name) parentOpt.selected = true;
            container.appendChild(parentOpt);

            const group = document.createElement('optgroup');
            group.label = '\u00A0\u00A0' + displayName;  // 缩进表示从属
            node.children.forEach(child => renderNode(child, 1, group));
            container.appendChild(group);
        } else {
            const option = document.createElement('option');
            option.value = label.id;
            option.textContent = indent + displayName + count;
            if (selectedLabel === label.id || selectedLabel === label.name) option.selected = true;
            container.appendChild(option);
            // 更深层子节点继续缩进
            node.children.forEach(child => renderNode(child, depth + 1, container));
        }
    }

    topLevel.forEach(node => renderNode(node, 0, select));

    return select;
}

// 更新表格中 Claude 的分类结果（只更新 pending-claude 的行）
function updateTableWithClaudeResults(classifications) {
    classifications.forEach(result => {
        const row = document.querySelector(`tr[data-email-id="${result.email_id}"]`);
        if (row) {
            const select = row.querySelector('.label-select');
            if (select && result.label && select.classList.contains('pending-claude')) {
                select.value = result.label;
                select.classList.remove('pending-claude');
                select.classList.add('claude-classified');

                // Claude 改了分类后，重新判断重要性
                // archive / 账单类 → 不重要
                const unimportantLabels = ['archive', 'Finance', 'Technology'];
                const importantLabels   = ['Operations', 'People & Education', 'Travel'];
                const starBtn = row.querySelector('.star-btn');
                if (starBtn) {
                    let important = starBtn.dataset.important === '1';
                    if (unimportantLabels.includes(result.label)) important = false;
                    if (importantLabels.includes(result.label))   important = true;
                    starBtn.dataset.important = important ? '1' : '0';
                    starBtn.textContent = important ? '★' : '☆';
                    if (important) row.classList.add('row-important');
                    else           row.classList.remove('row-important');
                }
            }
        }
    });
}

// 全选/取消全选
function toggleSelectAll() {
    const selectAll = document.getElementById('select-all');
    const checkboxes = document.querySelectorAll('.email-checkbox');
    checkboxes.forEach(cb => cb.checked = selectAll.checked);
    updateButtonStates();
}

// 更新按钮状态
function updateButtonStates() {
    // 无需额外操作，执行按钮始终可用
}

// 执行批量分类
async function executeClassification() {
    const rows = document.querySelectorAll('#email-tbody tr[data-email-id]');
    const actions = [];

    rows.forEach(row => {
        const emailId = row.dataset.emailId;
        const label = row.querySelector('.label-select').value;

        if (label === 'archive') {
            actions.push({ email_id: emailId, action: 'archive' });
        } else if (label !== 'inbox') {
            actions.push({ email_id: emailId, action: 'move', label: label });
        } else {
            actions.push({ email_id: emailId, action: 'mark-read' });
        }
    });

    if (actions.length === 0) {
        showNotification('没有需要执行的操作', 'info');
        return;
    }

    showLoading(`正在处理 ${actions.length} 封邮件...`);

    try {
        const response = await fetch('/api/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(actions)
        });

        const data = await response.json();
        hideLoading();

        if (data.success) {
            const parts = [];
            if (data.archived > 0) parts.push(`归档 ${data.archived}`);
            if (data.moved > 0) parts.push(`移动 ${data.moved}`);
            if (data.kept_in_inbox > 0) parts.push(`保留 inbox ${data.kept_in_inbox}`);
            if (data.failures > 0) parts.push(`失败 ${data.failures}`);
            const summary = parts.length ? parts.join('，') : `${data.processed} 封`;
            showNotification(`执行完成：${summary}`, data.failures > 0 ? 'error' : 'success');
            if (data.failures > 0 && data.failure_details && data.failure_details[0]) {
                console.error('Execute failures:', data.failure_details);
            }

            // 移除已处理的行，保留 inbox 的邮件
            actions.filter(a => a.action !== 'mark-read').forEach(a => {
                const row = document.querySelector(`tr[data-email-id="${a.email_id}"]`);
                const detailRow = document.getElementById(`detail-${a.email_id}`);
                if (row) row.remove();
                if (detailRow) detailRow.remove();
            });

            // 如果全空了，显示提示
            const remaining = document.querySelectorAll('#email-tbody tr[data-email-id]').length;
            if (remaining === 0) {
                document.getElementById('email-tbody').innerHTML =
                    '<tr><td colspan="6" class="empty-message">点击"获取邮件"开始</td></tr>';
                document.getElementById('execute-btn').disabled = true;
            }
            updateStatus(`分类完成，剩余 ${remaining} 封邮件保留在 Inbox`);
        } else {
            showNotification('执行失败: ' + data.error, 'error');
        }
    } catch (error) {
        hideLoading();
        console.error('Error executing classification:', error);
        showNotification('执行失败', 'error');
    }
}

// 根据纠错日志更新分类规则
async function updateRules() {
    const btn = document.getElementById('update-rules-btn');
    btn.disabled = true;
    showLoading('正在分析纠错日志并更新规则...');
    try {
        const response = await fetch('/api/update-rules', { method: 'POST' });
        const data = await response.json();
        hideLoading();
        if (data.success) {
            showNotification(data.message, 'success');
        } else {
            showNotification(data.error, 'error');
        }
    } catch (e) {
        hideLoading();
        showNotification('更新失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

// 退订邮件列表
async function unsubscribeEmail(emailId, checkbox) {
    checkbox.disabled = true;
    try {
        const response = await fetch(`/api/unsubscribe/${emailId}`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showNotification('退订成功：' + (data.detail || ''), 'success');
            checkbox.title = '已退订';
        } else if (data.method === 'manual' && data.url) {
            showNotification('需手动退订，正在打开链接...', 'info');
            window.open(data.url, '_blank', 'noopener');
            checkbox.checked = false;
            checkbox.disabled = false;
        } else {
            showNotification('退订失败：' + (data.detail || data.error || ''), 'error');
            checkbox.checked = false;
            checkbox.disabled = false;
        }
    } catch (e) {
        showNotification('退订请求失败', 'error');
        checkbox.checked = false;
        checkbox.disabled = false;
    }
}

// 工具函数

function showLoading(text = '加载中...') {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
}

function updateStatus(text) {
    document.getElementById('status').textContent = text;
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.classList.add('notification', type);
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.remove();
    }, 4000);
}

function formatEmailDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr);
        const now = new Date();
        const diffMs = now - d;
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffDays === 0) {
            // 今天：只显示时间
            return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        } else if (diffDays < 7) {
            // 7天内：周几 + 时间
            const dow = ['周日','周一','周二','周三','周四','周五','周六'][d.getDay()];
            return `${dow} ${d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
        } else if (d.getFullYear() === now.getFullYear()) {
            // 今年：月/日
            return `${d.getMonth()+1}月${d.getDate()}日`;
        } else {
            // 更早：年/月/日
            return `${d.getFullYear()}/${d.getMonth()+1}/${d.getDate()}`;
        }
    } catch(e) {
        return dateStr;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== Claude Usage =====

const fmt = n => n >= 1_000_000 ? (n/1_000_000).toFixed(1)+'M'
                : n >= 1_000     ? (n/1_000).toFixed(0)+'K'
                : String(n);

function barClass(pct) {
    if (pct > 90) return 'danger';
    if (pct > 70) return 'warning';
    return '';
}

async function loadUsage() {
    try {
        // 并行请求 snapshot（真实 %）和 token 统计
        const [snapRes, tokenRes] = await Promise.all([
            fetch('/api/usage-snapshot'),
            fetch('/api/usage'),
        ]);
        const snap   = await snapRes.json();
        const tokens = await tokenRes.json();

        // ── 真实 % 进度条 ──
        if (snap.success) {
            setBar('bar-session',  'val-session',  snap.session_pct, '', '会话');
            setBar('bar-week-pct', 'val-week-pct', snap.week_pct,  'week', '本周');

            const resetEl = document.getElementById('usage-reset-times');
            if (snap.session_reset || snap.week_reset) {
                resetEl.innerHTML =
                    (snap.session_reset ? `<span>会话重置: ${snap.session_reset}</span>` : '') +
                    (snap.week_reset    ? `<span>周重置: ${snap.week_reset}</span>` : '');
            }
            // 更新时间
            if (snap.updated_at) {
                const ago = Math.round((Date.now() - new Date(snap.updated_at)) / 60000);
                document.querySelector('.usage-label').title = `更新于 ${ago} 分钟前`;
            }
        }

        // ── Token sparkline ──
        if (tokens.success) {
            const sparkEl = document.getElementById('sparkline');
            sparkEl.innerHTML = '';
            const days = Object.entries(tokens.daily).sort(([a],[b]) => a.localeCompare(b));
            const todayStr = new Date().toISOString().slice(0,10);
            const maxVal = Math.max(...days.map(([,v]) => v), 1);
            days.forEach(([date, val]) => {
                const bar = document.createElement('div');
                bar.className = 'spark-bar' + (date === todayStr ? ' today' : '');
                bar.style.height = Math.max(2, Math.round((val / maxVal) * 24)) + 'px';
                const dow = ['日','一','二','三','四','五','六'][new Date(date + 'T12:00:00').getDay()];
                bar.title = `周${dow}: ${fmt(val)} output tokens`;
                sparkEl.appendChild(bar);
            });
        }

    } catch (e) {
        console.error('Usage load failed', e);
    }
}

function setBar(barId, valId, pct, extraClass, label) {
    const fill = document.getElementById(barId);
    const valEl = document.getElementById(valId);
    if (pct === null || pct === undefined) {
        fill.style.width = '0%';
        valEl.textContent = '—';
        return;
    }
    fill.style.width = Math.min(100, pct) + '%';
    fill.className = 'usage-bar-fill ' + extraClass + ' ' + barClass(pct);
    valEl.textContent = pct + '%';
}

// ===== Usage 快照更新 =====

async function refreshUsageFromCLI() {
    const btn = document.getElementById('usage-refresh-btn');
    btn.textContent = '…';
    btn.disabled = true;
    try {
        const res = await fetch('/api/usage-refresh', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            await loadUsage();
            showNotification('Usage 已刷新', 'success');
        } else {
            showNotification('刷新失败: ' + data.error, 'error');
        }
    } catch (e) {
        showNotification('刷新失败', 'error');
    } finally {
        btn.textContent = '↻';
        btn.disabled = false;
    }
}

function toggleLimitEditor() {
    const el = document.getElementById('limit-editor');
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function savePcts() {
    const sessionPct = parseFloat(document.getElementById('input-session-pct').value);
    const weekPct    = parseFloat(document.getElementById('input-week-pct').value);
    const body = {};
    if (!isNaN(sessionPct)) body.session_pct = sessionPct;
    if (!isNaN(weekPct))    body.week_pct    = weekPct;
    if (Object.keys(body).length === 0) return;

    try {
        await fetch('/api/usage-snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        document.getElementById('limit-editor').style.display = 'none';
        document.getElementById('input-session-pct').value = '';
        document.getElementById('input-week-pct').value = '';
        loadUsage();
        showNotification('已更新', 'success');
    } catch (e) {
        showNotification('保存失败', 'error');
    }
}

// ===== 深色主题 =====

function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    applyTheme(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('theme', next);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.getElementById('theme-toggle').textContent = theme === 'dark' ? '☀️' : '🌙';
}

// 切换 Gmail 星标（同步到 Gmail STARRED）
async function toggleImportance(btn, row, email) {
    const wasStarred = btn.dataset.important === '1';
    const nowStarred = !wasStarred;

    // 立即更新 UI
    btn.dataset.important = nowStarred ? '1' : '0';
    btn.textContent = nowStarred ? '★' : '☆';
    btn.title = nowStarred ? 'Gmail 已加星标（点击取消）' : '点击加 Gmail 星标';
    btn.disabled = true;

    if (nowStarred) row.classList.add('row-important');
    else            row.classList.remove('row-important');

    // 调 Gmail API
    const endpoint = nowStarred ? `/api/star/${email.id}` : `/api/unstar/${email.id}`;
    try {
        const res = await fetch(endpoint, { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            // 回滚
            btn.dataset.important = wasStarred ? '1' : '0';
            btn.textContent = wasStarred ? '★' : '☆';
            if (wasStarred) row.classList.add('row-important');
            else            row.classList.remove('row-important');
            showNotification('星标同步失败: ' + data.error, 'error');
        }
    } catch (e) {
        showNotification('星标同步失败', 'error');
    } finally {
        btn.disabled = false;
    }

    // 同时记录到本地日志
    fetch('/api/log-importance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            email_id: email.id, subject: email.subject,
            sender: email.sender, sender_email: email.sender_email,
            label: row.querySelector('.label-select')?.value || '',
            original: wasStarred, new_value: nowStarred,
        })
    }).catch(() => {});
}

// 保存附件到本地目录
async function saveAttachment(emailId, att, btn) {
    const isImage = att.mimeType.startsWith('image/');
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = '⏳ 保存中...';

    try {
        const res = await fetch(`/api/email/${emailId}/attachment/${att.attachmentId}/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: att.filename,
                mimeType: att.mimeType,
                save_dir: isImage ? '~/Downloads/Photos/School' : '~/Downloads',
            })
        });
        const data = await res.json();
        if (data.success) {
            btn.textContent = '✓ 已保存';
            btn.style.color = 'var(--accent, #4a90e2)';
            showNotification(`已保存: ${data.path.replace(/.*\/Downloads/, '~/Downloads')}`, 'success');
        } else {
            btn.textContent = orig;
            btn.disabled = false;
            showNotification('保存失败: ' + data.error, 'error');
        }
    } catch (e) {
        btn.textContent = orig;
        btn.disabled = false;
        showNotification('保存失败', 'error');
    }
}

// 记录用户手动分类变更（fire-and-forget）
function logCorrection(emailId, subject, sender, originalLabel, newLabel) {
    fetch('/api/log-correction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            email_id: emailId,
            subject: subject,
            sender: sender,
            original_label: originalLabel,
            new_label: newLabel,
        })
    }).catch(() => {});  // 静默失败，不影响主流程
}
