from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Member, MemberRole, ProviderSetting


class IdentityRepositoryProtocol(Protocol):
    async def get_member(self, member_id: UUID) -> Member | None: ...
    async def get_member_by_username(self, username: str) -> Member | None: ...
    async def list_members(self) -> Sequence[Member]: ...
    async def add_member(self, member: Member) -> Member: ...
    async def get_provider_setting(self, member_id: UUID) -> ProviderSetting | None: ...
    async def save_provider_setting(self, setting: ProviderSetting) -> ProviderSetting: ...
    async def delete_provider_setting(self, setting: ProviderSetting) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def refresh(self, instance: object, attribute_names: list[str] | None = None) -> None: ...
    async def lock_active_admins(self) -> Sequence[Member]: ...


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_member(self, member_id: UUID) -> Member | None:
        return await self.session.get(Member, member_id)

    async def get_member_by_username(self, username: str) -> Member | None:
        return await self.session.scalar(select(Member).where(Member.username == username))

    async def list_members(self) -> Sequence[Member]:
        return (await self.session.scalars(select(Member).order_by(Member.created_at))).all()

    async def add_member(self, member: Member) -> Member:
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_provider_setting(self, member_id: UUID) -> ProviderSetting | None:
        query = select(ProviderSetting).where(ProviderSetting.member_id == member_id)
        return await self.session.scalar(query)

    async def save_provider_setting(self, setting: ProviderSetting) -> ProviderSetting:
        self.session.add(setting)
        await self.session.flush()
        return setting

    async def delete_provider_setting(self, setting: ProviderSetting) -> None:
        await self.session.delete(setting)
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def refresh(self, instance: object, attribute_names: list[str] | None = None) -> None:
        await self.session.refresh(instance, attribute_names=attribute_names)

    async def lock_active_admins(self) -> Sequence[Member]:
        statement = (
            select(Member)
            .where(Member.role == MemberRole.ADMIN, Member.is_active.is_(True))
            .with_for_update()
        )
        return (await self.session.scalars(statement)).all()
