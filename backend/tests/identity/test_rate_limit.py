import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from redis.exceptions import RedisError

from app.modules.identity.rate_limit import (
    InMemoryLoginRateLimiter,
    LoginRateLimiter,
    LoginRateLimitExceeded,
    LoginRateLimits,
    LoginRateLimitUnavailable,
)


class FakeRedis:
    def __init__(self, response=None, error=None) -> None:
        self.response = response or [1, 60, 1, 60, 1, 60]
        self.error = error
        self.calls = []

    async def eval(self, script, numkeys, *keys_and_args):
        self.calls.append((script, numkeys, keys_and_args))
        if self.error:
            raise self.error
        return self.response


async def test_limiter_normalizes_username_without_storing_it_in_key() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(redis)

    await limiter.check("203.0.113.1", " Member ")
    first_keys = redis.calls[-1][2][:3]
    await limiter.check("203.0.113.1", "member")
    second_keys = redis.calls[-1][2][:3]

    assert first_keys == second_keys
    assert all("member" not in key for key in first_keys)


async def test_limiter_rejects_exceeded_bucket() -> None:
    limiter = LoginRateLimiter(FakeRedis(response=[6, 41, 1, 59, 1, 58]))

    with pytest.raises(LoginRateLimitExceeded) as exc_info:
        await limiter.check("203.0.113.1", "member")

    assert exc_info.value.retry_after == 59


async def test_limiter_fails_closed_when_redis_is_unavailable() -> None:
    limiter = LoginRateLimiter(FakeRedis(error=RedisError("unavailable")))

    with pytest.raises(LoginRateLimitUnavailable):
        await limiter.check("203.0.113.1", "member")


async def test_in_memory_limiter_matches_normalized_pair_window() -> None:
    now = [100.0]
    limiter = InMemoryLoginRateLimiter(
        LoginRateLimits(per_ip_username=2, per_ip=100, per_username=100),
        clock=lambda: now[0],
    )

    await limiter.check("203.0.113.1", " Member ")
    await limiter.check("203.0.113.1", "member")
    with pytest.raises(LoginRateLimitExceeded):
        await limiter.check("203.0.113.1", "MEMBER")

    now[0] += 61
    await limiter.check("203.0.113.1", "member")


def test_in_memory_limiter_is_thread_safe() -> None:
    limiter = InMemoryLoginRateLimiter(
        LoginRateLimits(per_ip_username=5, per_ip=100, per_username=100)
    )

    def attempt() -> bool:
        try:
            asyncio.run(limiter.check("203.0.113.1", "member"))
        except LoginRateLimitExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=10) as executor:
        accepted = list(executor.map(lambda _: attempt(), range(10)))

    assert accepted.count(True) == 5
    assert accepted.count(False) == 5
