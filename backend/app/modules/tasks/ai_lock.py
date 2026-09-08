"""Redis-backed per-member lease for billable AI calls."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from redis.exceptions import RedisError

from app.core.ai_limits import AI_LOCK_LEASE_SECONDS


class RedisLockClient(Protocol):
    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> object: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...


class MemberAiCallBusyError(RuntimeError):
    pass


class AiLockUnavailableError(RuntimeError):
    pass


_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(slots=True)
class MemberAiLease:
    client: RedisLockClient
    key: str
    token: str

    async def __aenter__(self) -> "MemberAiLease":
        return self

    async def __aexit__(self, *_: object) -> None:
        try:
            await self.client.eval(_RELEASE_SCRIPT, 1, self.key, self.token)
        except RedisError:
            # The bounded lease expires without deleting a newer owner's token.
            return


class MemberAiCallLock:
    def __init__(
        self, client: RedisLockClient, *, lease_seconds: int = AI_LOCK_LEASE_SECONDS
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("AI lock lease must be positive")
        self._client = client
        self._lease_seconds = lease_seconds

    async def acquire(self, member_id: UUID) -> MemberAiLease:
        key = f"douyin-caption:member-ai-call:{member_id}"
        token = uuid4().hex
        try:
            acquired = await self._client.set(
                key,
                token,
                nx=True,
                ex=self._lease_seconds,
            )
        except RedisError as exc:
            raise AiLockUnavailableError("AI concurrency control is unavailable") from exc
        if not acquired:
            raise MemberAiCallBusyError("The member already has an AI call in progress")
        return MemberAiLease(self._client, key, token)


@dataclass(slots=True)
class InMemoryMemberAiLease:
    owner: "InMemoryMemberAiCallLock"
    member_id: UUID
    token: str

    async def __aenter__(self) -> "InMemoryMemberAiLease":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.owner.release(self.member_id, self.token)


class InMemoryMemberAiCallLock:
    """Process-local development fallback; it does not coordinate multiple workers."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._tokens: dict[UUID, str] = {}

    async def acquire(self, member_id: UUID) -> InMemoryMemberAiLease:
        token = uuid4().hex
        async with self._guard:
            if member_id in self._tokens:
                raise MemberAiCallBusyError("The member already has an AI call in progress")
            self._tokens[member_id] = token
        return InMemoryMemberAiLease(self, member_id, token)

    async def release(self, member_id: UUID, token: str) -> None:
        async with self._guard:
            if self._tokens.get(member_id) == token:
                del self._tokens[member_id]


# The fallback must be shared by every request handled by this application process.
IN_MEMORY_MEMBER_AI_CALL_LOCK = InMemoryMemberAiCallLock()
