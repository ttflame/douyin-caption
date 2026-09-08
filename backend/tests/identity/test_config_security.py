import pytest
from pydantic import ValidationError

from app.core.config import Settings


def settings(**overrides):
    values = {
        "app_secret_key": "a" * 32,
        "key_encryption_secret": "b" * 32,
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    values.update(overrides)
    return Settings(**values)


def test_key_encryption_secret_rejects_weak_or_placeholder_values() -> None:
    with pytest.raises(ValidationError):
        settings(key_encryption_secret="short")
    with pytest.raises(ValidationError):
        settings(key_encryption_secret="replace-with-" + "x" * 32)


def test_legacy_secret_requires_explicit_migration_flag() -> None:
    configured = settings(
        key_encryption_secret="legacy-secret",
        allow_legacy_weak_key_encryption_secret=True,
    )

    assert configured.key_encryption_secret == "legacy-secret"


def test_production_rejects_in_memory_coordination() -> None:
    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        settings(app_env="production", allow_in_memory_coordination=True)


def test_development_can_explicitly_enable_in_memory_coordination() -> None:
    configured = settings(app_env="development", allow_in_memory_coordination=True)

    assert configured.allow_in_memory_coordination
