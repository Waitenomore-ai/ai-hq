from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_hq.auth.sessions import create_session, resolve_session, revoke_session
from ai_hq.db import Base


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_session_stores_only_token_digest_and_resolves_valid_token():
    db = make_session()
    raw_token, record = create_session(db, lifetime_hours=12)
    db.commit()

    assert raw_token not in record.token_digest
    assert len(record.token_digest) == 64
    assert resolve_session(db, raw_token) is not None


def test_expired_and_revoked_sessions_do_not_resolve():
    db = make_session()
    raw_token, record = create_session(db, lifetime_hours=12)
    db.commit()

    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert resolve_session(db, raw_token) is None

    second_token, second_record = create_session(db, lifetime_hours=12)
    db.commit()
    assert revoke_session(db, second_token) is True
    db.commit()
    assert second_record.revoked_at is not None
    assert resolve_session(db, second_token) is None
