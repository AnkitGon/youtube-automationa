import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # captions API
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"


def _token_path() -> str:
    from moduli.paths import config_path
    return config_path(TOKEN_FILE)


def _creds_path() -> str:
    from moduli.paths import config_path
    return config_path(CREDENTIALS_FILE)


def get_credentials() -> Credentials:
    creds = None
    token_path = _token_path()
    creds_path = _creds_path()
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path)
        except (ValueError, OSError):
            creds = None  # token corrotto → nuovo login

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # refresh token revocato/scaduto → serve un nuovo login interattivo
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(creds_path):
            raise FileNotFoundError(f"{creds_path} non trovato")
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return creds
