import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_hq.models.admin_session import AdminSession


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def create_session(db: Session, *, lifetime_hours: int) -> tuple[str, AdminSession]:
    raw_token = secrets.token_urlsafe(48)
    record = AdminSession(
        token_digest=_digest(raw_token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=lifetime_hours),
    )
    db.add(record)
    db.flush()
    return raw_token, record


def resolve_session(db: Session, token: str) -> AdminSession | None:
    if not token:
        return None
    record = db.scalar(select(AdminSession).where(AdminSession.token_digest == _digest(token)))
    if record is None or record.revoked_at is not None:
        return None
    if _utc(record.expires_at) <= datetime.now(UTC):
        return None
    return record


def revoke_session(db: Session, token: str) -> bool:
    record = db.scalar(select(AdminSession).where(AdminSession.token_digest == _digest(token)))
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = datetime.now(UTC)
    db.flush()
    return True
