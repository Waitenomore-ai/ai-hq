from redis import Redis
from redis.exceptions import RedisError

from ai_hq.config import get_settings


def redis_ping() -> bool:
    try:
        client = Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return bool(client.ping())
    except RedisError:
        return False
