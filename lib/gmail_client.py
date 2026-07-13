"""Gmail API wrapper - all API interactions go through here."""

import re
from typing import List, Optional
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from models import EmailSummary


def get_service(creds: Credentials):
    """Build Gmail API service."""
    return build('gmail', 'v1', credentials=creds)


def list_labels(service) -> List[dict]:
    """List all Gmail labels. Returns basic info immediately; counts fetched separately."""
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    return [
        {
            'id': l['id'],
            'name': l['name'],
            'type': l.get('type', 'user'),
            'messages_total': 0,  # fetched separately via list_labels_with_counts
        }
        for l in labels
    ]


def list_labels_with_counts(service) -> List[dict]:
    """Fetch all label details including message counts (slow, use with disk cache)."""
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    detailed = []
    for l in labels:
        try:
            detail = service.users().labels().get(userId='me', id=l['id']).execute()
            detailed.append({
                'id': detail['id'],
                'name': detail['name'],
                'type': detail.get('type', 'user'),
                'messages_total': detail.get('messagesTotal', 0),
            })
        except Exception:
            detailed.append({'id': l['id'], 'name': l['name'], 'type': l.get('type', 'user'), 'messages_total': 0})
    return detailed


def resolve_label_id(service, label_name: str) -> Optional[str]:
    """Resolve a label name to its ID. Case-insensitive."""
    labels = list_labels(service)
    for l in labels:
        if l['name'].lower() == label_name.lower():
            return l['id']
    return None


def fetch_emails(service, query: str = "is:unread in:inbox", max_results: int = 50) -> List[EmailSummary]:
    """Fetch emails matching query, return structured summaries."""
    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return []

    summaries = []
    for msg_stub in messages:
        msg = service.users().messages().get(
            userId='me',
            id=msg_stub['id'],
            format='metadata',
            metadataHeaders=['From', 'Subject', 'Date', 'List-Unsubscribe', 'List-Unsubscribe-Post']
        ).execute()

        headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
        sender = headers.get('From', '')
        sender_email = _extract_email(sender)
        unsubscribe = headers.get('List-Unsubscribe', '')

        summaries.append(EmailSummary(
            id=msg['id'],
            thread_id=msg.get('threadId', ''),
            subject=headers.get('Subject', '(no subject)'),
            sender=sender,
            sender_email=sender_email,
            date=headers.get('Date', ''),
            snippet=msg.get('snippet', ''),
            labels=msg.get('labelIds', []),
            has_unsubscribe=bool(unsubscribe),
            unsubscribe_link=unsubscribe if unsubscribe else None,
        ))

    return summaries


def move_to_label(service, msg_id: str, label_id: str, remove_inbox: bool = True) -> dict:
    """Move an email to a label. By default also removes from inbox."""
    body = {'addLabelIds': [label_id]}
    if remove_inbox:
        body['removeLabelIds'] = ['INBOX']
    service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
    return {'email_id': msg_id, 'action': 'move', 'success': True, 'label_id': label_id}


def mark_as_read(service, msg_ids: List[str]) -> dict:
    """Mark one or more emails as read."""
    if len(msg_ids) == 1:
        service.users().messages().modify(
            userId='me', id=msg_ids[0], body={'removeLabelIds': ['UNREAD']}
        ).execute()
    else:
        service.users().messages().batchModify(
            userId='me', body={'ids': msg_ids, 'removeLabelIds': ['UNREAD']}
        ).execute()
    return {'email_ids': msg_ids, 'action': 'mark-read', 'success': True}


def archive(service, msg_ids: List[str]) -> dict:
    """Archive emails (remove INBOX label)."""
    if len(msg_ids) == 1:
        service.users().messages().modify(
            userId='me', id=msg_ids[0], body={'removeLabelIds': ['INBOX']}
        ).execute()
    else:
        service.users().messages().batchModify(
            userId='me', body={'ids': msg_ids, 'removeLabelIds': ['INBOX']}
        ).execute()
    return {'email_ids': msg_ids, 'action': 'archive', 'success': True}


def get_unsubscribe_info(service, msg_id: str) -> dict:
    """Get unsubscribe header info for an email."""
    msg = service.users().messages().get(
        userId='me', id=msg_id, format='metadata',
        metadataHeaders=['List-Unsubscribe', 'List-Unsubscribe-Post']
    ).execute()
    headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
    return {
        'list_unsubscribe': headers.get('List-Unsubscribe', ''),
        'list_unsubscribe_post': headers.get('List-Unsubscribe-Post', ''),
    }


def send_email(service, to: str, subject: str = '', body: str = '') -> dict:
    """Send a simple email (used for mailto: unsubscribe)."""
    import base64
    from email.mime.text import MIMEText

    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId='me', body={'raw': raw}).execute()
    return {'sent_to': to, 'success': True}


def _extract_email(sender: str) -> str:
    """Extract email address from 'Name <email>' format."""
    match = re.search(r'<([^>]+)>', sender)
    if match:
        return match.group(1)
    # Might be just a plain email
    if '@' in sender:
        return sender.strip()
    return sender
