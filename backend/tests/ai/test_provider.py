import asyncio
import json

import httpx
import pytest

from app.modules.ai.dto import CompletionRequest, Message
from app.modules.ai.errors import AiError, AiErrorCode
from app.modules.ai.provider import OpenAICompatibleProvider, ProviderConfig


def request() -> CompletionRequest:
    return CompletionRequest(model="gpt-test", messages=[Message(role="user", content="hello")])


@pytest.mark.asyncio
async def test_provider_sends_compatible_request_and_parses_safe_metadata() -> None:
    async def handler(incoming: httpx.Request) -> httpx.Response:
        assert incoming.url.path == "/v1/chat/completions"
        assert incoming.headers["authorization"] == "Bearer top-secret"
        assert incoming.extensions["timeout"]["read"] == 240
        body = json.loads(incoming.content)
        assert body["model"] == "gpt-test"
        return httpx.Response(
            200,
            headers={"x-request-id": "req-123"},
            json={
                "choices": [{"message": {"content": "成品"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    provider = OpenAICompatibleProvider(
        ProviderConfig(api_key="top-secret", base_url="https://provider.example/v1"), client
    )
    result = await provider.complete(request())
    await client.aclose()

    assert result.text == "成品"
    assert result.provider_request_id == "req-123"
    assert result.usage.input_tokens == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (401, {"error": {"message": "key=top-secret"}}, AiErrorCode.AUTHENTICATION_FAILED, False),
        (429, {"error": {"code": "insufficient_quota"}}, AiErrorCode.INSUFFICIENT_QUOTA, True),
        (429, {"error": {"code": "rate_limit"}}, AiErrorCode.RATE_LIMITED, True),
        (500, {"error": {"message": "internal secret"}}, AiErrorCode.PROVIDER_ERROR, True),
    ],
)
async def test_provider_normalizes_errors_without_response_body(
    status: int, body: dict, code: AiErrorCode, retryable: bool
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    )
    provider = OpenAICompatibleProvider(
        ProviderConfig(api_key="top-secret", base_url="https://provider.example/v1"), client
    )
    with pytest.raises(AiError) as caught:
        await provider.complete(request())
    await client.aclose()

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    serialized = json.dumps(caught.value.as_dict(), ensure_ascii=False)
    assert "top-secret" not in serialized
    assert "internal secret" not in serialized


@pytest.mark.asyncio
async def test_provider_rejects_malformed_success_response() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": []}))
    )
    provider = OpenAICompatibleProvider(
        ProviderConfig(api_key="secret", base_url="https://provider.example/v1"), client
    )
    with pytest.raises(AiError) as caught:
        await provider.complete(request())
    await client.aclose()
    assert caught.value.code == AiErrorCode.INVALID_RESPONSE


def test_provider_config_masks_key_and_validates_url() -> None:
    config = ProviderConfig(api_key="top-secret")
    assert config.timeout_seconds == 240
    assert "top-secret" not in repr(config)
    with pytest.raises(ValueError):
        ProviderConfig(api_key="x", base_url="not-a-url")


async def test_html_success_response_identifies_wrong_api_endpoint() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<!doctype html><html>Private website content</html>",
            )
        )
    ) as client:
        provider = OpenAICompatibleProvider(
            ProviderConfig(api_key="secret", base_url="https://provider.example"),
            client,
        )
        with pytest.raises(AiError) as caught:
            await provider.complete(request())
    assert caught.value.code == AiErrorCode.INVALID_ENDPOINT
    assert not caught.value.retryable
    assert "/v1" in caught.value.message
    assert "Private website content" not in str(caught.value.as_dict())


async def test_provider_enforces_configured_deadline_and_cancels_request() -> None:
    cancelled = asyncio.Event()

    async def handler(incoming):
        assert incoming.extensions["timeout"]["read"] == 0.02
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            ProviderConfig(api_key="secret", timeout_seconds=0.02), client
        )
        with pytest.raises(AiError) as caught:
            await provider.complete(request())
    assert cancelled.is_set()
    assert caught.value.code == AiErrorCode.TIMEOUT
    assert caught.value.retryable
