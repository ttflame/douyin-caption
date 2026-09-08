import importlib
from types import SimpleNamespace

from app.modules.identity.rate_limit import InMemoryLoginRateLimiter, LoginRateLimiter

identity_router = importlib.import_module("app.modules.identity.router")


async def test_dependency_uses_in_memory_limiter_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        identity_router,
        "get_settings",
        lambda: SimpleNamespace(
            allow_in_memory_coordination=True,
            redis_url="redis://unused:6379/0",
        ),
    )

    dependency = identity_router.get_login_rate_limiter()
    limiter = await anext(dependency)
    await dependency.aclose()

    assert isinstance(limiter, InMemoryLoginRateLimiter)


async def test_dependency_keeps_redis_as_default(monkeypatch) -> None:
    monkeypatch.setattr(
        identity_router,
        "get_settings",
        lambda: SimpleNamespace(
            allow_in_memory_coordination=False,
            redis_url="redis://localhost:6379/0",
        ),
    )

    dependency = identity_router.get_login_rate_limiter()
    limiter = await anext(dependency)
    await dependency.aclose()

    assert isinstance(limiter, LoginRateLimiter)
