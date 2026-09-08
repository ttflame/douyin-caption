import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.modules.identity.bootstrap import (
    BootstrapConflictError,
    BootstrapStatus,
    bootstrap_first_admin,
)
from app.modules.identity.models import Member, MemberRole, ProviderSetting
from app.modules.identity.security import PasswordService

IDENTITY_TABLES = [Member.__table__, ProviderSetting.__table__]


async def test_bootstrap_creates_first_admin_and_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=IDENTITY_TABLES)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as session:
        created = await bootstrap_first_admin(
            session,
            username="admin",
            display_name="Administrator",
            password="secure-password",
        )
    async with sessions() as session:
        repeated = await bootstrap_first_admin(
            session,
            username="admin",
            display_name="Changed name",
            password="different-password",
        )
        stored = await session.scalar(select(Member).where(Member.username == "admin"))

    assert created.status == BootstrapStatus.CREATED
    assert repeated.status == BootstrapStatus.ALREADY_EXISTS
    assert stored is not None
    assert stored.display_name == "Administrator"
    assert PasswordService().verify("secure-password", stored.password_hash)
    assert not PasswordService().verify("different-password", stored.password_hash)
    await engine.dispose()


async def test_bootstrap_refuses_second_admin() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=IDENTITY_TABLES)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as session:
        await bootstrap_first_admin(
            session,
            username="first-admin",
            display_name="First",
            password="secure-password",
        )
    async with sessions() as session:
        with pytest.raises(BootstrapConflictError, match="already exists"):
            await bootstrap_first_admin(
                session,
                username="second-admin",
                display_name="Second",
                password="secure-password",
            )

    await engine.dispose()


async def test_bootstrap_refuses_existing_member_username() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=IDENTITY_TABLES)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    passwords = PasswordService()
    async with sessions() as session:
        session.add(
            Member(
                username="member",
                display_name="Member",
                password_hash=passwords.hash("secure-password"),
                role=MemberRole.MEMBER,
                is_active=True,
            )
        )
        await session.commit()
        with pytest.raises(BootstrapConflictError, match="non-administrator"):
            await bootstrap_first_admin(
                session,
                username="member",
                display_name="Admin",
                password="secure-password",
            )

    await engine.dispose()
