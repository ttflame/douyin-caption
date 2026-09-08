from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.provider_url import ProviderUrlPolicyError
from app.modules.identity.errors import IdentityError
from app.modules.identity.models import Member, MemberRole, ProviderSetting
from app.modules.identity.provider import ProviderTestOutcome
from app.modules.identity.schemas import (
    MemberCreate,
    MemberUpdate,
    ProviderConnectionTestRequest,
    ProviderSettingWrite,
    ProviderTimeoutWrite,
)
from app.modules.identity.security import ApiKeyCipher, JwtService, PasswordService
from app.modules.identity.services import IdentityService

NOW = datetime.now(UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.members: dict[UUID, Member] = {}
        self.settings: dict[UUID, ProviderSetting] = {}
        self.commits = 0
        self.active_admins_override = None

    async def get_member(self, member_id):
        return self.members.get(member_id)

    async def get_member_by_username(self, username):
        return next((item for item in self.members.values() if item.username == username), None)

    async def list_members(self):
        return list(self.members.values())

    async def add_member(self, member):
        member.id = member.id or uuid4()
        member.created_at = member.created_at or NOW
        member.updated_at = member.updated_at or NOW
        self.members[member.id] = member
        return member

    async def get_provider_setting(self, member_id):
        return self.settings.get(member_id)

    async def save_provider_setting(self, setting):
        setting.id = getattr(setting, "id", None) or uuid4()
        setting.created_at = getattr(setting, "created_at", None) or NOW
        setting.updated_at = NOW
        self.settings[setting.member_id] = setting
        return setting

    async def delete_provider_setting(self, setting):
        del self.settings[setting.member_id]

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, instance, attribute_names=None):
        pass

    async def lock_active_admins(self):
        if self.active_admins_override is not None:
            return self.active_admins_override
        return [
            item
            for item in self.members.values()
            if item.role == MemberRole.ADMIN and item.is_active
        ]


class FakeTester:
    def __init__(self) -> None:
        self.received = None

    async def test(self, api_key, base_url, model_identifier, *, timeout_seconds):
        self.received = (api_key, base_url, model_identifier)
        self.received_timeout = timeout_seconds
        return ProviderTestOutcome(True, "ok", "Connection succeeded")


class AllowPublicUrlPolicy:
    async def validate(self, value):
        return value.rstrip("/")


class RejectPrivateUrlPolicy:
    async def validate(self, _value):
        raise ProviderUrlPolicyError(
            "provider_url_private_address", "Provider URL must resolve only to public addresses"
        )


@pytest.fixture
def identity():
    repository = FakeRepository()
    passwords = PasswordService()
    tester = FakeTester()
    service = IdentityService(
        repository,
        passwords,
        JwtService("token-secret-that-is-at-least-32-characters"),
        ApiKeyCipher("encryption-secret"),
        tester,
        AllowPublicUrlPolicy(),
    )
    return service, repository, passwords, tester


def member(passwords, *, role=MemberRole.MEMBER, active=True, username="member"):
    return Member(
        id=uuid4(),
        username=username,
        display_name=username.title(),
        password_hash=passwords.hash("password123"),
        role=role,
        is_active=active,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_authentication_rejects_disabled_member(identity) -> None:
    service, repository, passwords, _ = identity
    disabled = member(passwords, active=False)
    repository.members[disabled.id] = disabled

    with pytest.raises(IdentityError) as exc_info:
        await service.authenticate(disabled.username, "password123")

    assert exc_info.value.code == "invalid_credentials"
    assert exc_info.value.status_code == 401


async def test_non_admin_cannot_create_or_update_member(identity) -> None:
    service, _, passwords, _ = identity
    ordinary = member(passwords)
    payload = MemberCreate(username="new-user", display_name="New", password="password123")

    with pytest.raises(IdentityError) as exc_info:
        await service.create_member(ordinary, payload)
    assert exc_info.value.code == "admin_required"

    with pytest.raises(IdentityError):
        await service.update_member(ordinary, uuid4(), MemberUpdate(is_active=False))


async def test_admin_cannot_disable_self(identity) -> None:
    service, repository, passwords, _ = identity
    admin = member(passwords, role=MemberRole.ADMIN, username="admin")
    repository.members[admin.id] = admin

    with pytest.raises(IdentityError) as exc_info:
        await service.update_member(admin, admin.id, MemberUpdate(is_active=False))

    assert exc_info.value.code == "cannot_disable_self"
    assert admin.is_active


async def test_last_active_admin_cannot_be_disabled(identity) -> None:
    service, repository, passwords, _ = identity
    actor = member(passwords, role=MemberRole.ADMIN, username="actor")
    target = member(passwords, role=MemberRole.ADMIN, username="target")
    repository.members[target.id] = target
    repository.active_admins_override = [target]

    with pytest.raises(IdentityError) as exc_info:
        await service.update_member(actor, target.id, MemberUpdate(is_active=False))

    assert exc_info.value.code == "last_admin_required"
    assert target.is_active


async def test_admin_can_create_member_with_hashed_password(identity) -> None:
    service, repository, passwords, _ = identity
    admin = member(passwords, role=MemberRole.ADMIN, username="admin")

    created = await service.create_member(
        admin,
        MemberCreate(username="new-user", display_name="New User", password="password123"),
    )

    assert created.password_hash != "password123"
    assert passwords.verify("password123", created.password_hash)
    assert repository.members[created.id] is created


async def test_provider_setting_is_scoped_and_never_returns_plain_key(identity) -> None:
    service, repository, passwords, _ = identity
    owner = member(passwords, username="owner")
    other = member(passwords, username="other")

    response = await service.put_provider_setting(
        owner,
        ProviderSettingWrite(
            api_key="sk-1234567890abcdef",
            base_url="https://api.example.com/",
            model_id=" custom/vendor-model ",
        ),
    )

    assert response.api_key_masked == "sk-********cdef"
    assert response.model_id == "custom/vendor-model"
    assert response.timeout_seconds == 240
    assert (await service.get_provider_setting(owner)).model_id == "custom/vendor-model"
    assert "1234567890" not in response.model_dump_json()
    assert repository.settings[owner.id].encrypted_api_key != b"sk-1234567890abcdef"
    with pytest.raises(IdentityError) as exc_info:
        await service.get_provider_setting(other)
    assert exc_info.value.code == "provider_setting_not_found"


async def test_provider_connection_uses_saved_secret_without_exposing_it(identity) -> None:
    service, repository, passwords, tester = identity
    owner = member(passwords)
    await service.put_provider_setting(
        owner,
        ProviderSettingWrite(
            api_key="sk-secret-value",
            base_url="https://api.example.com",
            model_id="gpt-test",
        ),
    )

    result = await service.test_provider(owner, ProviderConnectionTestRequest())

    assert result.success
    assert tester.received == ("sk-secret-value", "https://api.example.com", "gpt-test")
    assert "sk-secret-value" not in result.model_dump_json()


async def test_timeout_updates_preserve_connection_and_are_member_scoped(identity) -> None:
    service, repository, passwords, tester = identity
    owner = member(passwords)
    await service.put_provider_setting(
        owner,
        ProviderSettingWrite(
            api_key="secret",
            base_url="https://api.example.com",
            model_id="model",
            timeout_seconds=300,
        ),
    )
    saved = repository.settings[owner.id]
    original_connection = (saved.encrypted_api_key, saved.base_url, saved.model_id)
    assert (await service.get_provider_setting(owner)).timeout_seconds == 300
    result = await service.patch_provider_timeout(owner, ProviderTimeoutWrite(timeout_seconds=600))
    assert result.timeout_seconds == 600
    assert (saved.encrypted_api_key, saved.base_url, saved.model_id) == original_connection
    await service.test_provider(owner, ProviderConnectionTestRequest())
    assert tester.received_timeout == 600
    await service.test_provider(owner, ProviderConnectionTestRequest(timeout_seconds=240))
    assert tester.received_timeout == 240
    assert saved.timeout_seconds == 600
    with pytest.raises(IdentityError) as caught:
        await service.patch_provider_timeout(
            member(passwords), ProviderTimeoutWrite(timeout_seconds=240)
        )
    assert caught.value.status_code == 404


@pytest.mark.parametrize("timeout", [0, 9, 601, 1.5, "240", True, None])
def test_timeout_patch_rejects_invalid_limits(timeout) -> None:
    with pytest.raises(ValidationError):
        ProviderTimeoutWrite(timeout_seconds=timeout)


def test_timeout_patch_cannot_change_connection() -> None:
    with pytest.raises(ValidationError):
        ProviderTimeoutWrite(timeout_seconds=240, base_url="https://other.example")


@pytest.mark.parametrize("model_id", ["", "   ", "x" * 151])
@pytest.mark.parametrize("schema", [ProviderSettingWrite, ProviderConnectionTestRequest])
def test_invalid_model_names_are_rejected(schema, model_id) -> None:
    with pytest.raises(ValidationError):
        schema(api_key="sk-secret-value", base_url="https://api.example.com", model_id=model_id)


async def test_connection_uses_manually_entered_model(identity) -> None:
    service, _, passwords, tester = identity
    result = await service.test_provider(
        member(passwords),
        ProviderConnectionTestRequest(
            api_key="sk-secret-value",
            base_url="https://api.example.com",
            model_id=" vendor/custom-model ",
        ),
    )
    assert result.success
    assert tester.received == ("sk-secret-value", "https://api.example.com", "vendor/custom-model")


async def test_provider_url_is_revalidated_before_connection(identity) -> None:
    service, repository, passwords, tester = identity
    owner = member(passwords)
    service.provider_url_policy = RejectPrivateUrlPolicy()

    with pytest.raises(IdentityError) as exc_info:
        await service.test_provider(
            owner,
            ProviderConnectionTestRequest(
                api_key="sk-secret-value",
                base_url="https://internal.example/v1",
                model_id="gpt-test",
            ),
        )

    assert exc_info.value.code == "provider_url_private_address"
    assert tester.received is None
