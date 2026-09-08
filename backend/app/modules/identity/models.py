from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ai_limits import DEFAULT_RESPONSE_TIMEOUT_SECONDS
from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MemberRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class Member(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "members"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=MemberRole.MEMBER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    provider_setting: Mapped[ProviderSetting | None] = relationship(
        back_populates="member", cascade="all, delete-orphan", uselist=False
    )


class ProviderSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_settings"

    member_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    encrypted_api_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_id: Mapped[str] = mapped_column(String(150), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_RESPONSE_TIMEOUT_SECONDS, server_default="240", nullable=False
    )

    member: Mapped[Member] = relationship(back_populates="provider_setting")
