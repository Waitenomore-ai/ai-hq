import hashlib
import hmac

from sqlalchemy.orm import Session
from starlette.requests import Request

from ai_hq.auth.sessions import resolve_session
from ai_hq.config import Settings
from ai_hq.models.admin_session import AdminSession

SESSION_COOKIE = "ai_hq_session"


def encode_session_cookie(raw_token: str, secret: str) -> str:
    signature = hmac.new(secret.encode(), raw_token.encode(), hashlib.sha256).hexdigest()
    return f"{raw_token}.{signature}"


def decode_session_cookie(value: str, secret: str) -> str | None:
    try:
        raw_token, signature = value.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), raw_token.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return raw_token


def resolve_request_session(
    request: Request, db: Session, settings: Settings
) -> tuple[str, AdminSession] | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie or not settings.session_secret:
        return None
    raw_token = decode_session_cookie(cookie, settings.session_secret)
    if raw_token is None:
        return None
    record = resolve_session(db, raw_token)
    if record is None:
        return None
    return raw_token, record
