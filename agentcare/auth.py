"""Small in-process authentication layer for the local dashboard."""

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from agentcare.config import AUTH_PASSWORD, AUTH_USERNAME

TOKEN_TTL = timedelta(hours=12)
_tokens = {}


def authenticate(username, password):
    if not hmac.compare_digest(username, AUTH_USERNAME):
        return None
    if not hmac.compare_digest(password, AUTH_PASSWORD):
        return None

    token = secrets.token_urlsafe(32)
    _tokens[token] = datetime.now(timezone.utc) + TOKEN_TTL
    return token


def is_valid_token(token):
    expires_at = _tokens.get(token)
    if expires_at is None:
        return False
    if expires_at <= datetime.now(timezone.utc):
        _tokens.pop(token, None)
        return False
    return True
