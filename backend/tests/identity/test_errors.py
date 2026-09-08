from unittest.mock import Mock

from app.modules.identity.errors import IdentityError, identity_exception_handler


async def test_identity_error_uses_api_contract_shape() -> None:
    response = await identity_exception_handler(
        Mock(), IdentityError("admin_required", "Administrator access is required", 403)
    )

    assert response.status_code == 403
    assert response.body == (
        b'{"error":{"code":"admin_required","message":'
        b'"Administrator access is required","details":{}}}'
    )
