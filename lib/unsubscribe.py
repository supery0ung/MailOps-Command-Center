"""Unsubscribe logic - parse List-Unsubscribe header and execute."""

import re
import urllib.request
import urllib.parse
from typing import Optional
from gmail_client import get_unsubscribe_info, send_email


def attempt_unsubscribe(service, msg_id: str) -> dict:
    """Attempt to unsubscribe from an email.

    Tries in order:
    1. One-click HTTP POST (if List-Unsubscribe-Post header present)
    2. mailto: link (sends unsubscribe email)
    3. Returns HTTP URL for manual unsubscribe
    """
    info = get_unsubscribe_info(service, msg_id)
    unsub_header = info.get('list_unsubscribe', '')
    unsub_post = info.get('list_unsubscribe_post', '')

    if not unsub_header:
        return {
            'email_id': msg_id,
            'action': 'unsubscribe',
            'success': False,
            'detail': 'No List-Unsubscribe header found',
        }

    http_url = _extract_url(unsub_header, 'https') or _extract_url(unsub_header, 'http')
    mailto = _extract_mailto(unsub_header)

    # Method 1: One-click POST (RFC 8058)
    if http_url and unsub_post:
        try:
            data = unsub_post.encode('utf-8')
            req = urllib.request.Request(http_url, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {
                    'email_id': msg_id,
                    'action': 'unsubscribe',
                    'success': True,
                    'method': 'one-click-post',
                    'detail': f'POST to {http_url} returned {resp.status}',
                }
        except Exception as e:
            # Fall through to other methods
            pass

    # Method 2: mailto
    if mailto:
        try:
            parsed = urllib.parse.urlparse(f'mailto:{mailto}')
            to_addr = parsed.path
            params = urllib.parse.parse_qs(parsed.query)
            subject = params.get('subject', ['Unsubscribe'])[0]
            body = params.get('body', [''])[0]
            send_email(service, to_addr, subject, body)
            return {
                'email_id': msg_id,
                'action': 'unsubscribe',
                'success': True,
                'method': 'mailto',
                'detail': f'Sent unsubscribe email to {to_addr}',
            }
        except Exception as e:
            pass

    # Method 3: Return URL for manual unsubscribe
    if http_url:
        return {
            'email_id': msg_id,
            'action': 'unsubscribe',
            'success': False,
            'method': 'manual',
            'detail': f'Please visit manually: {http_url}',
            'url': http_url,
        }

    return {
        'email_id': msg_id,
        'action': 'unsubscribe',
        'success': False,
        'detail': 'Could not parse unsubscribe header',
    }


def _extract_url(header: str, scheme: str) -> Optional[str]:
    """Extract a URL with given scheme from List-Unsubscribe header."""
    pattern = rf'<({scheme}://[^>]+)>'
    match = re.search(pattern, header)
    return match.group(1) if match else None


def _extract_mailto(header: str) -> Optional[str]:
    """Extract mailto address from List-Unsubscribe header."""
    match = re.search(r'<mailto:([^>]+)>', header)
    return match.group(1) if match else None
