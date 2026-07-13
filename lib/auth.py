"""OAuth2 authentication for Gmail API."""

import os
import sys
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')


def get_credentials() -> Credentials:
    """Get valid OAuth2 credentials, refreshing or re-authorizing as needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception:
            # Refresh failed, need to re-authorize
            pass

    if not os.path.exists(CREDENTIALS_FILE):
        print(json.dumps({
            "error": "credentials.json not found",
            "detail": f"Please download OAuth client credentials from Google Cloud Console and save as {CREDENTIALS_FILE}",
        }))
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def _save_token(creds: Credentials):
    """Save credentials to token.json."""
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())


def authenticate():
    """Run auth flow and print status."""
    creds = get_credentials()
    print(json.dumps({"status": "authenticated", "token_file": TOKEN_FILE}))
    return creds
