from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str = Field(min_length=32)
    allow_legacy_weak_key_encryption_secret: bool = False
    key_encryption_secret: str
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    allow_in_memory_coordination: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("key_encryption_secret")
    @classmethod
    def validate_key_encryption_secret(cls, value: str, info: ValidationInfo) -> str:
        legacy_allowed = bool(info.data.get("allow_legacy_weak_key_encryption_secret"))
        looks_placeholder = "replace-with" in value.casefold()
        if not legacy_allowed and (len(value) < 32 or looks_placeholder):
            raise ValueError(
                "KEY_ENCRYPTION_SECRET must be at least 32 random characters and not a placeholder"
            )
        return value

    @model_validator(mode="after")
    def reject_in_memory_coordination_in_production(self) -> "Settings":
        if self.app_env.casefold() == "production" and self.allow_in_memory_coordination:
            raise ValueError("In-memory coordination cannot be enabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
