from app.modules.identity.router import router
from app.modules.identity.schemas import MemberPublic, ProviderSettingPublic


def test_router_exposes_only_identity_and_configuration_routes() -> None:
    paths = {route.path for route in router.routes}

    assert paths == {
        "/auth/login",
        "/auth/me",
        "/auth/change-password",
        "/admin/members",
        "/admin/members/{member_id}",
        "/settings/provider",
        "/settings/provider/test",
    }
    assert all("task" not in path and "version" not in path for path in paths)


def test_public_dtos_cannot_serialize_passwords_or_plain_api_keys() -> None:
    assert "password" not in MemberPublic.model_fields
    assert "password_hash" not in MemberPublic.model_fields
    assert "api_key" not in ProviderSettingPublic.model_fields
    assert "encrypted_api_key" not in ProviderSettingPublic.model_fields
    assert "api_key_masked" in ProviderSettingPublic.model_fields
