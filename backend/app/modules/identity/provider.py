import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.ai_limits import DEFAULT_RESPONSE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ProviderTestOutcome:
    success: bool
    code: str
    message: str


class ProviderConnectionTester(Protocol):
    async def test(
        self,
        api_key: str,
        base_url: str,
        model_identifier: str,
        *,
        timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    ) -> ProviderTestOutcome: ...


class OpenAICompatibleConnectionTester:
    async def test(
        self,
        api_key: str,
        base_url: str,
        model_identifier: str,
        *,
        timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    ) -> ProviderTestOutcome:
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with (
                asyncio.timeout(timeout_seconds),
                httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout_seconds, connect=10, write=30, pool=10)
                ) as client,
            ):
                response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        except (httpx.TimeoutException, TimeoutError):
            return ProviderTestOutcome(False, "provider_timeout", "Provider request timed out")
        except httpx.HTTPError:
            return ProviderTestOutcome(False, "provider_network_error", "Provider is unreachable")

        if response.status_code in {401, 403}:
            return ProviderTestOutcome(
                False, "provider_auth_failed", "Provider rejected the API key"
            )
        if response.status_code == 429:
            return ProviderTestOutcome(
                False, "provider_rate_limited", "Provider rate limit reached"
            )
        if response.is_error:
            return ProviderTestOutcome(False, "provider_error", "Provider connection test failed")

        if "text/html" in response.headers.get("content-type", "").lower():
            return ProviderTestOutcome(
                False,
                "provider_invalid_endpoint",
                "请求地址返回了网页，请检查 API 地址是否包含正确路径（通常为 /v1）。",
            )

        try:
            model_ids = {item.get("id") for item in response.json().get("data", [])}
        except (ValueError, AttributeError):
            return ProviderTestOutcome(
                False, "provider_invalid_response", "Provider returned invalid data"
            )
        if model_identifier not in model_ids:
            return ProviderTestOutcome(False, "model_unavailable", "Selected model is unavailable")
        return ProviderTestOutcome(True, "ok", "Connection succeeded")
