from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.ai_limits import (
    DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    MAX_RESPONSE_TIMEOUT_SECONDS,
    MIN_RESPONSE_TIMEOUT_SECONDS,
)
from app.core.provider_url import validate_provider_base_url_structure
from app.modules.identity.models import MemberRole


class MemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    role: MemberRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    member: MemberPublic


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class MemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    role: MemberRole = MemberRole.MEMBER


class MemberUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


ModelIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]


ResponseTimeout = Annotated[
    int, Field(strict=True, ge=MIN_RESPONSE_TIMEOUT_SECONDS, le=MAX_RESPONSE_TIMEOUT_SECONDS)
]


class ProviderTimeoutWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: ResponseTimeout


class ProviderSettingWrite(BaseModel):
    api_key: str = Field(min_length=1, max_length=1000)
    base_url: str = Field(min_length=1, max_length=500)
    model_id: ModelIdentifier
    timeout_seconds: ResponseTimeout = DEFAULT_RESPONSE_TIMEOUT_SECONDS

    @field_validator("api_key")
    @classmethod
    def strip_api_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("API key cannot be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_provider_base_url_structure(value)


class ProviderSettingPublic(BaseModel):
    id: UUID
    base_url: str
    model_id: str
    timeout_seconds: int
    api_key_masked: str
    created_at: datetime
    updated_at: datetime


class ProviderConnectionTestRequest(BaseModel):
    api_key: str | None = Field(default=None, min_length=1, max_length=1000)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    model_id: ModelIdentifier | None = None
    timeout_seconds: ResponseTimeout | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return validate_provider_base_url_structure(value) if value is not None else None


class ProviderConnectionTestResult(BaseModel):
    success: bool
    code: str
    message: str


class MessageResponse(BaseModel):
    message: str
