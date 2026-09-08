from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Member, MemberRole
from app.modules.identity.schemas import MemberCreate
from app.modules.identity.security import PasswordService


class BootstrapStatus(StrEnum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    status: BootstrapStatus
    username: str
    is_active: bool


class BootstrapConflictError(RuntimeError):
    pass


async def bootstrap_first_admin(
    session: AsyncSession,
    *,
    username: str,
    display_name: str,
    password: str,
) -> BootstrapResult:
    """Create the only initial administrator without mutating an existing account."""
    payload = MemberCreate(
        username=username,
        display_name=display_name,
        password=password,
        role=MemberRole.ADMIN,
    )
    await _serialize_postgresql_bootstrap(session)

    existing_username = await session.scalar(
        select(Member).where(Member.username == payload.username)
    )
    if existing_username is not None:
        if existing_username.role != MemberRole.ADMIN:
            raise BootstrapConflictError(
                "The bootstrap username already belongs to a non-administrator account"
            )
        return BootstrapResult(
            BootstrapStatus.ALREADY_EXISTS,
            existing_username.username,
            existing_username.is_active,
        )

    existing_admin = await session.scalar(
        select(Member).where(Member.role == MemberRole.ADMIN).limit(1)
    )
    if existing_admin is not None:
        raise BootstrapConflictError(
            "An administrator already exists; use the administration API to add accounts"
        )

    administrator = Member(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=PasswordService().hash(password),
        role=MemberRole.ADMIN,
        is_active=True,
    )
    session.add(administrator)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BootstrapConflictError(
            "Administrator bootstrap conflicted with another account creation"
        ) from exc
    return BootstrapResult(BootstrapStatus.CREATED, administrator.username, True)


async def _serialize_postgresql_bootstrap(session: AsyncSession) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(1847074281)"))
