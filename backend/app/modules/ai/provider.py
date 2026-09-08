"""OpenAI-compatible chat-completions provider adapter."""

import asyncio
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.ai_limits import DEFAULT_RESPONSE_TIMEOUT_SECONDS, MAX_RESPONSE_TIMEOUT_SECONDS

from .dto import CompletionRequest, CompletionResult, ProviderUsage
from .errors import AiError, AiErrorCode, error_for_status


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: SecretStr
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = Field(
        default=DEFAULT_RESPONSE_TIMEOUT_SECONDS, gt=0, le=MAX_RESPONSE_TIMEOUT_SECONDS
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        return value.rstrip("/")


class Provider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
        }
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name or "structured_output",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }

        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout_seconds, connect=10, write=30, pool=10)
        )
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                response = await client.post(
                    f"{self._config.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(
                        self._config.timeout_seconds, connect=10, write=30, pool=10
                    ),
                )
            if response.is_error:
                raise self._safe_http_error(response)
            if "text/html" in response.headers.get("content-type", "").lower():
                raise AiError(AiErrorCode.INVALID_ENDPOINT, retryable=False)
            return self._parse_response(response)
        except AiError:
            raise
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AiError(AiErrorCode.TIMEOUT, retryable=True) from exc
        except httpx.RequestError as exc:
            raise AiError(AiErrorCode.NETWORK_ERROR, retryable=True) from exc
        finally:
            if owned_client:
                await client.aclose()

    @staticmethod
    def _safe_http_error(response: httpx.Response) -> AiError:
        provider_code = None
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                value = body["error"].get("code")
                provider_code = value if isinstance(value, str) else None
        except ValueError:
            pass
        return error_for_status(response.status_code, provider_code)

    @staticmethod
    def _parse_response(response: httpx.Response) -> CompletionResult:
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            usage = body.get("usage") or {}
            return CompletionResult(
                text=content,
                provider_request_id=response.headers.get("x-request-id") or body.get("id"),
                usage=ProviderUsage(
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AiError(AiErrorCode.INVALID_RESPONSE, retryable=True) from exc
