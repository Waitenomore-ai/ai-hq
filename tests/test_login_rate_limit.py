from ai_hq.auth.rate_limit import LoginRateLimiter


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1


def test_rate_limiter_blocks_at_threshold_and_sets_ttl():
    redis = FakeRedis()
    limiter = LoginRateLimiter(redis, max_attempts=2, window_seconds=60)

    assert limiter.is_blocked("203.0.113.10") is False
    limiter.record_failure("203.0.113.10")
    assert limiter.is_blocked("203.0.113.10") is False
    limiter.record_failure("203.0.113.10")
    assert limiter.is_blocked("203.0.113.10") is True
    assert 60 in redis.ttls.values()


def test_rate_limiter_clear_removes_failures_and_hides_raw_identity():
    redis = FakeRedis()
    limiter = LoginRateLimiter(redis, max_attempts=2, window_seconds=60)
    identity = "198.51.100.7"

    limiter.record_failure(identity)
    assert all(identity not in key for key in redis.values)
    limiter.clear(identity)
    assert limiter.is_blocked(identity) is False
