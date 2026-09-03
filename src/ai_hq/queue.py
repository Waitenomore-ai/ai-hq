from ai_hq.config import get_settings


def redis_ping() -> bool:
    try:
        from redis import Redis

        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
        return bool(client.ping())
    except Exception:
        return False
