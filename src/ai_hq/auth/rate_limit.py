import hashlib


class LoginRateLimiter:
    def __init__(self, redis_client, *, max_attempts: int = 5, window_seconds: int = 900):
        self.redis = redis_client
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    def _key(self, identity: str) -> str:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"ai-hq:auth:failed:{digest}"

    def is_blocked(self, identity: str) -> bool:
        value = self.redis.get(self._key(identity))
        return int(value or 0) >= self.max_attempts

    def record_failure(self, identity: str) -> None:
        key = self._key(identity)
        count = self.redis.incr(key)
        if count == 1:
            self.redis.expire(key, self.window_seconds)

    def clear(self, identity: str) -> None:
        self.redis.delete(self._key(identity))
