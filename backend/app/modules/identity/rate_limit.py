import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError


class RateLimitClient(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class LoginAttemptLimiter(Protocol):
    async def check(self, client_ip: str, username: str) -> None: ...


class LoginRateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many login attempts")
        self.retry_after = max(retry_after, 1)


class LoginRateLimitUnavailable(RuntimeError):
    pass


_RATE_LIMIT_SCRIPT = """
local results = {}
for index = 1, 3 do
  local count = redis.call('incr', KEYS[index])
  if count == 1 then redis.call('expire', KEYS[index], ARGV[1]) end
  results[index * 2 - 1] = count
  results[index * 2] = redis.call('ttl', KEYS[index])
end
return results
"""


@dataclass(frozen=True, slots=True)
class LoginRateLimits:
    window_seconds: int = 60
    per_ip_username: int = 5
    per_ip: int = 30
    per_username: int = 15


class LoginRateLimiter:
    """Fail closed when Redis cannot verify whether a login is allowed."""

    def __init__(self, client: RateLimitClient, limits: LoginRateLimits | None = None) -> None:
        self._client = client
        self._limits = limits or LoginRateLimits()

    async def check(self, client_ip: str, username: str) -> None:
        keys = _rate_keys(client_ip, username)
        try:
            raw = await self._client.eval(
                _RATE_LIMIT_SCRIPT,
                3,
                *keys,
                self._limits.window_seconds,
            )
            values = [int(value) for value in raw]  # type: ignore[arg-type]
        except (RedisError, TypeError, ValueError) as exc:
            raise LoginRateLimitUnavailable("Login rate limiting is unavailable") from exc
        if len(values) != 6:
            raise LoginRateLimitUnavailable("Login rate limiting returned invalid data")
        counts = values[0], values[2], values[4]
        thresholds = (
            self._limits.per_ip_username,
            self._limits.per_ip,
            self._limits.per_username,
        )
        if any(count > threshold for count, threshold in zip(counts, thresholds, strict=True)):
            retry_after = max(values[1], values[3], values[5], 1)
            raise LoginRateLimitExceeded(retry_after)


class InMemoryLoginRateLimiter:
    """Process-local development fallback with bounded, lock-protected state."""

    def __init__(
        self,
        limits: LoginRateLimits | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits or LoginRateLimits()
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, float]] = {}
        self._checks = 0

    async def check(self, client_ip: str, username: str) -> None:
        now = self._clock()
        keys = _rate_keys(client_ip, username)
        with self._lock:
            self._checks += 1
            if self._checks % 1000 == 0:
                self._buckets = {
                    key: bucket for key, bucket in self._buckets.items() if bucket[1] > now
                }
            counts: list[int] = []
            retry_values: list[int] = []
            for key in keys:
                count, expires_at = self._buckets.get(key, (0, now + self._limits.window_seconds))
                if expires_at <= now:
                    count, expires_at = 0, now + self._limits.window_seconds
                count += 1
                self._buckets[key] = count, expires_at
                counts.append(count)
                retry_values.append(max(int(expires_at - now + 0.999), 1))
        thresholds = (
            self._limits.per_ip_username,
            self._limits.per_ip,
            self._limits.per_username,
        )
        if any(count > threshold for count, threshold in zip(counts, thresholds, strict=True)):
            raise LoginRateLimitExceeded(max(retry_values))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _rate_keys(client_ip: str, username: str) -> tuple[str, str, str]:
    normalized_username = username.strip().casefold()
    ip_digest = _digest(client_ip.strip())
    username_digest = _digest(normalized_username)
    return (
        f"douyin-caption:login:pair:{ip_digest}:{username_digest}",
        f"douyin-caption:login:ip:{ip_digest}",
        f"douyin-caption:login:username:{username_digest}",
    )
