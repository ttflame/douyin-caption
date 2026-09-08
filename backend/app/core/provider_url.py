import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit


class ProviderUrlPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


ResolvedAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressResolver = Callable[[str, int], Awaitable[set[ResolvedAddress]]]


def validate_provider_base_url_structure(value: str, *, production: bool = False) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized or any(character.isspace() for character in normalized):
        raise ProviderUrlPolicyError("provider_url_invalid", "Provider URL is invalid")
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ProviderUrlPolicyError("provider_url_invalid", "Provider URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderUrlPolicyError(
            "provider_url_invalid", "Provider URL must be an absolute HTTP(S) URL"
        )
    if production and parsed.scheme != "https":
        raise ProviderUrlPolicyError(
            "provider_url_https_required", "Provider URL must use HTTPS in production"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ProviderUrlPolicyError(
            "provider_url_credentials_forbidden", "Provider URL cannot contain credentials"
        )
    if parsed.query or parsed.fragment:
        raise ProviderUrlPolicyError(
            "provider_url_components_forbidden",
            "Provider URL cannot contain a query or fragment",
        )
    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ProviderUrlPolicyError(
            "provider_url_private_address", "Provider URL must resolve to a public address"
        )
    if port is not None and not 1 <= port <= 65535:
        raise ProviderUrlPolicyError("provider_url_invalid", "Provider URL port is invalid")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        return normalized
    _require_public({literal})
    return normalized


async def resolve_addresses(hostname: str, port: int) -> set[ResolvedAddress]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return {ipaddress.ip_address(record[4][0]) for record in records}


class ProviderUrlPolicy:
    """Validate provider destinations immediately before outbound use.

    DNS is checked here but resolved again by HTTP clients. Production deployments must also apply
    egress firewall or proxy rules to close that DNS-rebinding time-of-check gap.
    """

    def __init__(
        self,
        *,
        production: bool = False,
        resolver: AddressResolver = resolve_addresses,
    ) -> None:
        self._production = production
        self._resolver = resolver

    async def validate(self, value: str) -> str:
        normalized = validate_provider_base_url_structure(value, production=self._production)
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        if hostname is None:
            raise ProviderUrlPolicyError("provider_url_invalid", "Provider URL is invalid")
        try:
            literal = ipaddress.ip_address(hostname.rstrip("."))
        except ValueError:
            try:
                addresses = await self._resolver(
                    hostname.rstrip("."), parsed.port or (443 if parsed.scheme == "https" else 80)
                )
            except OSError as exc:
                raise ProviderUrlPolicyError(
                    "provider_url_unresolvable", "Provider URL hostname cannot be resolved"
                ) from exc
        else:
            addresses = {literal}
        _require_public(addresses)
        return normalized


def _require_public(addresses: set[ResolvedAddress]) -> None:
    if not addresses or any(not address.is_global for address in addresses):
        raise ProviderUrlPolicyError(
            "provider_url_private_address", "Provider URL must resolve only to public addresses"
        )
