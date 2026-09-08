from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.ai_limits import DEFAULT_RESPONSE_TIMEOUT_SECONDS
from app.core.provider_url import ProviderUrlPolicy, ProviderUrlPolicyError
from app.modules.identity.errors import IdentityError, not_found
from app.modules.identity.models import Member, MemberRole, ProviderSetting
from app.modules.identity.provider import ProviderConnectionTester
from app.modules.identity.repositories import IdentityRepositoryProtocol
from app.modules.identity.schemas import (
    MemberCreate,
    MemberUpdate,
    ProviderConnectionTestRequest,
    ProviderConnectionTestResult,
    ProviderSettingPublic,
    ProviderSettingWrite,
    ProviderTimeoutWrite,
)
from app.modules.identity.security import ApiKeyCipher, JwtService, PasswordService


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepositoryProtocol,
        passwords: PasswordService,
        tokens: JwtService,
        cipher: ApiKeyCipher,
        provider_tester: ProviderConnectionTester,
        provider_url_policy: ProviderUrlPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.passwords = passwords
        self.tokens = tokens
        self.cipher = cipher
        self.provider_tester = provider_tester
        self.provider_url_policy = provider_url_policy or ProviderUrlPolicy()

    async def authenticate(self, username: str, password: str) -> tuple[str, Member]:
        member = await self.repository.get_member_by_username(username.strip())
        password_hash = member.password_hash if member is not None else _DUMMY_PASSWORD_HASH
        password_valid = self.passwords.verify(password, password_hash)
        if member is None or not password_valid or not member.is_active:
            raise IdentityError("invalid_credentials", "Invalid username or password", 401)
        return self.tokens.issue(member.id), member

    async def authenticated_member(self, token: str) -> Member:
        try:
            claims = self.tokens.decode(token)
        except ValueError as exc:
            raise IdentityError("invalid_token", str(exc), 401) from exc
        member = await self.repository.get_member(claims.member_id)
        if member is None:
            raise IdentityError("invalid_token", "Access token member no longer exists", 401)
        if not member.is_active:
            raise IdentityError("member_disabled", "Member account is disabled", 403)
        return member

    @staticmethod
    def require_admin(member: Member) -> None:
        if member.role != MemberRole.ADMIN:
            raise IdentityError("admin_required", "Administrator access is required", 403)

    async def change_password(self, member: Member, current: str, new: str) -> None:
        if not self.passwords.verify(current, member.password_hash):
            raise IdentityError("invalid_current_password", "Current password is incorrect", 400)
        member.password_hash = self.passwords.hash(new)
        await self.repository.commit()

    async def create_member(self, actor: Member, data: MemberCreate) -> Member:
        self.require_admin(actor)
        if await self.repository.get_member_by_username(data.username):
            raise IdentityError("username_exists", "Username already exists", 409)
        member = Member(
            username=data.username,
            display_name=data.display_name,
            password_hash=self.passwords.hash(data.password),
            role=data.role,
            is_active=True,
        )
        try:
            await self.repository.add_member(member)
            await self.repository.commit()
            await self.repository.refresh(member)
        except IntegrityError as exc:
            await self.repository.rollback()
            raise IdentityError("username_exists", "Username already exists", 409) from exc
        return member

    async def update_member(self, actor: Member, member_id: UUID, data: MemberUpdate) -> Member:
        self.require_admin(actor)
        member = await self.repository.get_member(member_id)
        if member is None:
            raise not_found("member")
        updates = data.model_dump(exclude_unset=True)
        disabling_active_admin = (
            updates.get("is_active") is False
            and member.is_active
            and member.role == MemberRole.ADMIN
        )
        if disabling_active_admin:
            if member.id == actor.id:
                raise IdentityError(
                    "cannot_disable_self", "Administrators cannot disable their own account", 409
                )
            active_admins = await self.repository.lock_active_admins()
            if len(active_admins) <= 1:
                raise IdentityError(
                    "last_admin_required", "The last active administrator cannot be disabled", 409
                )
        for key, value in updates.items():
            setattr(member, key, value)
        await self.repository.commit()
        await self.repository.refresh(member)
        return member

    async def put_provider_setting(
        self, member: Member, data: ProviderSettingWrite
    ) -> ProviderSettingPublic:
        base_url = await self._validated_provider_url(data.base_url)
        setting = await self.repository.get_provider_setting(member.id)
        encrypted_key = self.cipher.encrypt(data.api_key)
        if setting is None:
            setting = ProviderSetting(
                member_id=member.id,
                encrypted_api_key=encrypted_key,
                base_url=base_url,
                model_id=data.model_id,
                timeout_seconds=data.timeout_seconds,
            )
        else:
            setting.encrypted_api_key = encrypted_key
            setting.base_url = base_url
            setting.model_id = data.model_id
            setting.timeout_seconds = data.timeout_seconds
        setting = await self.repository.save_provider_setting(setting)
        await self.repository.commit()
        await self.repository.refresh(setting)
        return self._provider_public(setting, data.api_key)

    async def patch_provider_timeout(
        self, member: Member, data: ProviderTimeoutWrite
    ) -> ProviderSettingPublic:
        setting = await self.repository.get_provider_setting(member.id)
        if setting is None:
            raise not_found("provider_setting")
        setting.timeout_seconds = data.timeout_seconds
        await self.repository.commit()
        await self.repository.refresh(setting)
        return self._provider_public(setting, self.cipher.decrypt(setting.encrypted_api_key))

    async def get_provider_setting(self, member: Member) -> ProviderSettingPublic:
        setting = await self.repository.get_provider_setting(member.id)
        if setting is None:
            raise not_found("provider_setting")
        api_key = self.cipher.decrypt(setting.encrypted_api_key)
        return self._provider_public(setting, api_key)

    async def delete_provider_setting(self, member: Member) -> None:
        setting = await self.repository.get_provider_setting(member.id)
        if setting is None:
            raise not_found("provider_setting")
        await self.repository.delete_provider_setting(setting)
        await self.repository.commit()

    async def test_provider(
        self, member: Member, data: ProviderConnectionTestRequest
    ) -> ProviderConnectionTestResult:
        saved = await self.repository.get_provider_setting(member.id)
        api_key = data.api_key
        base_url = data.base_url.rstrip("/") if data.base_url else None
        model_id = data.model_id
        timeout_seconds = data.timeout_seconds
        if saved is not None:
            api_key = api_key or self.cipher.decrypt(saved.encrypted_api_key)
            base_url = base_url or saved.base_url
            model_id = model_id or saved.model_id
            if timeout_seconds is None:
                timeout_seconds = saved.timeout_seconds
        if not api_key or not base_url or not model_id:
            raise IdentityError(
                "provider_settings_incomplete", "API key, base URL, and model are required", 400
            )
        base_url = await self._validated_provider_url(base_url)
        outcome = await self.provider_tester.test(
            api_key,
            base_url,
            model_id,
            timeout_seconds=timeout_seconds or DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        )
        return ProviderConnectionTestResult(
            success=outcome.success, code=outcome.code, message=outcome.message
        )

    async def _validated_provider_url(self, value: str) -> str:
        try:
            return await self.provider_url_policy.validate(value)
        except ProviderUrlPolicyError as exc:
            raise IdentityError(exc.code, exc.message, 400) from exc

    def _provider_public(self, setting: ProviderSetting, api_key: str) -> ProviderSettingPublic:
        return ProviderSettingPublic(
            id=setting.id,
            base_url=setting.base_url,
            model_id=setting.model_id,
            timeout_seconds=setting.timeout_seconds,
            api_key_masked=self.cipher.mask(api_key),
            created_at=setting.created_at,
            updated_at=setting.updated_at,
        )


_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$uOneBxs4NNG0Ziy+u4jhkA$"
    "CZQp9FnU2Chi0kgjBkqEVbfpP+t/ecPnM8outgmOMzo"
)
