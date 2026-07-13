"""
Gmail 客户端包装类 - 统一接口供 Web 应用使用
"""
import sys
import os

# 添加 lib 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from lib import gmail_client as gc
from lib.auth import get_credentials


class GmailClient:
    """Gmail API 客户端包装类"""

    def __init__(self):
        """初始化并获取凭证"""
        self.creds = get_credentials()
        self.service = gc.get_service(self.creds)

    def list_labels(self):
        """获取所有标签（基本信息，快速）"""
        return gc.list_labels(self.service)

    def list_labels_with_counts(self):
        """获取所有标签（含邮件数量，慢，用于磁盘缓存刷新）"""
        return gc.list_labels_with_counts(self.service)

    def fetch_emails(self, query="is:unread in:inbox", max_results=50):
        """
        获取邮件列表

        Returns:
            List of email dictionaries
        """
        email_summaries = gc.fetch_emails(self.service, query, max_results)

        # 转换为字典格式
        emails = []
        for summary in email_summaries:
            emails.append({
                "id": summary.id,
                "thread_id": summary.thread_id,
                "subject": summary.subject,
                "sender": summary.sender,
                "sender_email": summary.sender_email,
                "date": summary.date,
                "snippet": summary.snippet,
                "labels": summary.labels,
                "has_unsubscribe": summary.has_unsubscribe,
                "unsubscribe_link": summary.unsubscribe_link
            })
        return emails

    def get_email(self, email_id):
        """
        获取单封邮件的完整内容

        Returns:
            Email dictionary with full content
        """
        msg = self.service.users().messages().get(
            userId='me',
            id=email_id,
            format='full'
        ).execute()

        # 解析 headers
        headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}

        # 获取邮件正文（优先 HTML）
        body_html, body_text = self._get_email_body(msg)
        attachments = self._get_attachments(msg)

        return {
            "id": msg['id'],
            "thread_id": msg.get('threadId', ''),
            "subject": headers.get('Subject', '(no subject)'),
            "sender": headers.get('From', ''),
            "date": headers.get('Date', ''),
            "snippet": msg.get('snippet', ''),
            "body": body_text or body_html or msg.get('snippet', ''),
            "body_html": body_html,
            "body_text": body_text,
            "labels": msg.get('labelIds', []),
            "attachments": attachments,
        }

    def _get_email_body(self, msg):
        """从邮件中提取正文，返回 (html, text) 元组。内联图片 cid: 替换为 data URL。"""
        import base64
        import re

        html_body = None
        text_body = None
        # cid (without angle brackets) -> data URL
        cid_map = {}

        def decode_part(part):
            data = part.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            return None

        def extract_parts(parts):
            nonlocal html_body, text_body
            for part in parts:
                mime = part.get('mimeType', '')
                headers = {h['name'].lower(): h['value'] for h in part.get('headers', [])}
                content_id = headers.get('content-id', '')
                # strip angle brackets: <foo@bar> -> foo@bar
                if content_id:
                    content_id = content_id.strip('<> ')

                if mime == 'text/html' and not html_body:
                    html_body = decode_part(part)
                elif mime == 'text/plain' and not text_body:
                    text_body = decode_part(part)
                elif mime.startswith('image/') and content_id:
                    # Inline image: get data
                    body = part.get('body', {})
                    img_data = body.get('data', '')
                    if not img_data and body.get('attachmentId'):
                        try:
                            att = self.service.users().messages().attachments().get(
                                userId='me',
                                messageId=msg['id'],
                                id=body['attachmentId']
                            ).execute()
                            img_data = att.get('data', '')
                        except Exception:
                            pass
                    if img_data:
                        # Gmail uses URL-safe base64; convert to standard for data URL
                        standard_b64 = img_data.replace('-', '+').replace('_', '/')
                        cid_map[content_id] = f'data:{mime};base64,{standard_b64}'
                elif mime.startswith('multipart/') and 'parts' in part:
                    extract_parts(part['parts'])

        payload = msg.get('payload', {})
        mime_type = payload.get('mimeType', '')

        if 'parts' in payload:
            extract_parts(payload['parts'])
        elif mime_type == 'text/html':
            html_body = decode_part(payload)
        elif mime_type == 'text/plain':
            text_body = decode_part(payload)

        # Replace cid: references in HTML with data URLs
        if html_body and cid_map:
            def replace_cid(m):
                cid = m.group(1).strip()
                return 'src="' + cid_map.get(cid, m.group(0)[5:-1]) + '"'
            html_body = re.sub(r'src="cid:([^"]+)"', replace_cid, html_body, flags=re.IGNORECASE)

        return html_body, text_body

    def _get_attachments(self, msg):
        """收集邮件中的文件附件（排除内联图片）"""
        attachments = []

        def scan_parts(parts):
            for part in parts:
                mime = part.get('mimeType', '')
                headers = {h['name'].lower(): h['value'] for h in part.get('headers', [])}
                disposition = headers.get('content-disposition', '').lower()
                content_id = headers.get('content-id', '')
                filename = part.get('filename', '')
                body = part.get('body', {})
                attachment_id = body.get('attachmentId', '')

                # 只要有 filename 或明确是 attachment disposition 的才算附件
                is_attachment = bool(filename) or 'attachment' in disposition
                # 内联图片（有 content-id）跳过，已在 cid_map 处理
                is_inline_image = mime.startswith('image/') and content_id

                if is_attachment and not is_inline_image and attachment_id:
                    attachments.append({
                        'filename': filename or f'attachment.{mime.split("/")[-1]}',
                        'mimeType': mime,
                        'attachmentId': attachment_id,
                        'size': body.get('size', 0),
                    })

                if mime.startswith('multipart/') and 'parts' in part:
                    scan_parts(part['parts'])

        payload = msg.get('payload', {})
        if 'parts' in payload:
            scan_parts(payload['parts'])
        return attachments

    def get_attachment(self, email_id: str, attachment_id: str) -> dict:
        """获取附件数据，返回 {data: base64str, mimeType: str}"""
        # 先获取邮件元数据来确认 mimeType
        att = self.service.users().messages().attachments().get(
            userId='me',
            messageId=email_id,
            id=attachment_id
        ).execute()
        return {
            'data': att.get('data', ''),
            'size': att.get('size', 0),
        }

    def star_email(self, email_id: str):
        """给邮件加星标（同步到 Gmail STARRED）"""
        self.service.users().messages().modify(
            userId='me', id=email_id,
            body={'addLabelIds': ['STARRED']}
        ).execute()

    def unstar_email(self, email_id: str):
        """取消邮件星标"""
        self.service.users().messages().modify(
            userId='me', id=email_id,
            body={'removeLabelIds': ['STARRED']}
        ).execute()

    def batch_execute(self, actions):
        """
        批量执行操作

        Args:
            actions: List of action dicts
                [
                    {"action": "move", "email_id": "...", "label_name": "Finance"},
                    {"action": "mark-read", "email_id": "..."},
                    {"action": "archive", "email_id": "..."}
                ]

        Returns:
            List of results
        """
        results = []

        for action_dict in actions:
            try:
                action_type = action_dict["action"]
                email_id = action_dict["email_id"]

                if action_type == "move":
                    label_name = action_dict["label_name"]
                    # 解析 label ID
                    label_id = gc.resolve_label_id(self.service, label_name)
                    if not label_id:
                        label_id = label_name  # 如果找不到，假设已经是 ID

                    result = gc.move_to_label(self.service, email_id, label_id)
                    results.append(result)

                elif action_type == "mark-read":
                    result = gc.mark_as_read(self.service, [email_id])
                    results.append(result)

                elif action_type == "archive":
                    result = gc.archive(self.service, [email_id])
                    results.append(result)

                else:
                    results.append({
                        "email_id": email_id,
                        "action": action_type,
                        "success": False,
                        "error": f"Unknown action: {action_type}"
                    })

            except Exception as e:
                results.append({
                    "email_id": action_dict.get("email_id"),
                    "action": action_dict.get("action"),
                    "success": False,
                    "error": str(e)
                })

        return results
