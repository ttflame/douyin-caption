from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from app.core.ai_limits import AI_OPERATION_STALE_SECONDS, MAX_RESPONSE_TIMEOUT_SECONDS
from app.modules.tasks import router as task_router
from app.modules.tasks.ai_lock import (
    AiLockUnavailableError,
    InMemoryMemberAiCallLock,
    MemberAiCallBusyError,
    MemberAiCallLock,
)


class FakeRedis:
    def __init__(self, acquired=True, *, unavailable: bool = False) -> None:
        self.acquired = acquired
        self.unavailable = unavailable
        self.set_calls = []
        self.eval_calls = []

    async def set(self, name, value, *, nx, ex):
        if self.unavailable:
            raise ConnectionError("redis details")
        self.set_calls.append((name, value, nx, ex))
        return self.acquired

    async def eval(self, script, numkeys, *keys_and_args):
        self.eval_calls.append((script, numkeys, keys_and_args))
        return 1

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_member_lock_uses_bounded_owner_token_lease() -> None:
    redis = FakeRedis()
    member_id = uuid4()
    lease = await MemberAiCallLock(redis, lease_seconds=120).acquire(member_id)

    async with lease:
        pass

    key, token, nx, seconds = redis.set_calls[0]
    assert key.endswith(str(member_id))
    assert nx is True
    assert seconds == 120
    assert redis.eval_calls[0][2] == (key, token)


@pytest.mark.asyncio
async def test_member_lock_rejects_second_active_call() -> None:
    with pytest.raises(MemberAiCallBusyError):
        await MemberAiCallLock(FakeRedis(acquired=False)).acquire(uuid4())


async def test_default_lease_covers_longest_provider_request() -> None:
    redis = FakeRedis()
    async with await MemberAiCallLock(redis).acquire(uuid4()):
        lease_seconds = redis.set_calls[0][3]
        assert MAX_RESPONSE_TIMEOUT_SECONDS < lease_seconds < AI_OPERATION_STALE_SECONDS


@pytest.mark.asyncio
async def test_member_lock_fails_closed_when_redis_is_unavailable() -> None:
    with pytest.raises(AiLockUnavailableError, match="concurrency control"):
        await MemberAiCallLock(FakeRedis(unavailable=True)).acquire(uuid4())


@pytest.mark.asyncio
async def test_in_memory_lock_blocks_same_member_but_not_other_members() -> None:
    lock = InMemoryMemberAiCallLock()
    first_member = uuid4()
    first_lease = await lock.acquire(first_member)
    other_lease = await lock.acquire(uuid4())

    with pytest.raises(MemberAiCallBusyError):
        await lock.acquire(first_member)

    await other_lease.__aexit__()
    await first_lease.__aexit__()
    replacement = await lock.acquire(first_member)
    await replacement.__aexit__()


@pytest.mark.asyncio
async def test_dependency_reuses_process_lock_when_development_fallback_enabled(
    monkeypatch,
) -> None:
    settings = SimpleNamespace(
        app_env="development",
        allow_in_memory_coordination=True,
        redis_url="redis://unused",
    )
    monkeypatch.setattr(task_router, "get_settings", lambda: settings)

    first_dependency = task_router.get_member_ai_call_lock()
    second_dependency = task_router.get_member_ai_call_lock()
    first = await anext(first_dependency)
    second = await anext(second_dependency)
    assert first is task_router.IN_MEMORY_MEMBER_AI_CALL_LOCK
    assert second is first
    await first_dependency.aclose()
    await second_dependency.aclose()


@pytest.mark.asyncio
async def test_production_ignores_in_memory_fallback_switch(monkeypatch) -> None:
    settings = SimpleNamespace(
        app_env="production",
        allow_in_memory_coordination=True,
        redis_url="redis://production",
    )
    redis_client = FakeRedis()
    monkeypatch.setattr(task_router, "get_settings", lambda: settings)
    monkeypatch.setattr(
        task_router.Redis,
        "from_url",
        lambda *_args, **_kwargs: redis_client,
    )
    dependency = task_router.get_member_ai_call_lock()
    selected = await anext(dependency)
    assert isinstance(selected, MemberAiCallLock)
    await dependency.aclose()
