from collections.abc import Callable
from typing import Any

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_hq.config import get_settings
from ai_hq.db import get_engine

Probe = Callable[[], bool]


def database_probe() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def redis_probe() -> bool:
    try:
        client = Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return bool(client.ping())
    except RedisError:
        return False


def readiness_payload(database_ok: bool, redis_ok: bool) -> tuple[int, dict[str, Any]]:
    ready = database_ok and redis_ok
    return (
        200 if ready else 503,
        {
            "status": "ready" if ready else "not_ready",
            "database": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    )
