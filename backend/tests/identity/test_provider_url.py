import ipaddress

import pytest

from app.core.provider_url import (
    ProviderUrlPolicy,
    ProviderUrlPolicyError,
    validate_provider_base_url_structure,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1/v1",
        "http://[::1]/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?target=internal",
        "https://example.com/v1#fragment",
    ],
)
def test_structure_rejects_unsafe_provider_urls(url: str) -> None:
    with pytest.raises(ProviderUrlPolicyError):
        validate_provider_base_url_structure(url)


def test_production_requires_https() -> None:
    with pytest.raises(ProviderUrlPolicyError) as exc_info:
        validate_provider_base_url_structure("http://api.example.com/v1", production=True)

    assert exc_info.value.code == "provider_url_https_required"


async def test_policy_rejects_hostname_resolving_to_any_private_address() -> None:
    async def resolver(_hostname: str, _port: int):
        return {ipaddress.ip_address("203.0.113.10"), ipaddress.ip_address("10.0.0.2")}

    with pytest.raises(ProviderUrlPolicyError) as exc_info:
        await ProviderUrlPolicy(resolver=resolver).validate("https://api.example.com/v1")

    assert exc_info.value.code == "provider_url_private_address"


async def test_policy_accepts_public_resolution_and_normalizes_trailing_slash() -> None:
    async def resolver(_hostname: str, _port: int):
        return {ipaddress.ip_address("8.8.8.8")}

    result = await ProviderUrlPolicy(production=True, resolver=resolver).validate(
        "https://api.example.com/v1/"
    )

    assert result == "https://api.example.com/v1"
