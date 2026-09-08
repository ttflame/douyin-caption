"""Safe, provider-independent errors exposed by AI operations."""

from enum import StrEnum
from typing import Any


class AiErrorCode(StrEnum):
    AUTHENTICATION_FAILED = "provider_authentication_failed"
    INSUFFICIENT_QUOTA = "provider_insufficient_quota"
    RATE_LIMITED = "provider_rate_limited"
    INVALID_REQUEST = "provider_invalid_request"
    MODEL_UNAVAILABLE = "provider_model_unavailable"
    TIMEOUT = "provider_timeout"
    NETWORK_ERROR = "provider_network_error"
    INVALID_RESPONSE = "provider_invalid_response"
    PRESERVATION_FAILED = "locked_text_changed"
    INVALID_ENDPOINT = "provider_invalid_endpoint"
    PROVIDER_ERROR = "provider_error"


_MESSAGES = {
    AiErrorCode.AUTHENTICATION_FAILED: "模型服务鉴权失败，请检查 API Key。",
    AiErrorCode.INSUFFICIENT_QUOTA: "模型服务额度不足，请检查账户余额或配额。",
    AiErrorCode.RATE_LIMITED: "模型服务请求过于频繁，请稍后重试。",
    AiErrorCode.INVALID_REQUEST: "模型服务无法处理本次请求，请检查模型和内容设置。",
    AiErrorCode.MODEL_UNAVAILABLE: "所选模型暂时不可用，请稍后重试或联系管理员。",
    AiErrorCode.TIMEOUT: "模型服务响应超时，请稍后重试。",
    AiErrorCode.NETWORK_ERROR: "无法连接模型服务，请检查请求地址或网络。",
    AiErrorCode.INVALID_RESPONSE: "模型服务返回了无法识别的结果，请重试。",
    AiErrorCode.PRESERVATION_FAILED: "模型改动了保留文字，本次结果未保存，请重试。",
    AiErrorCode.INVALID_ENDPOINT: (
        "请求地址返回了网页，请检查 API 地址是否包含正确路径（通常为 /v1）。"
    ),
    AiErrorCode.PROVIDER_ERROR: "模型服务调用失败，请稍后重试。",
}


class AiError(Exception):
    def __init__(
        self,
        code: AiErrorCode,
        *,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = _MESSAGES[code]
        self.retryable = retryable
        self.details = details or {}
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": {"retryable": self.retryable, **self.details},
        }


def error_for_status(status_code: int, provider_code: str | None = None) -> AiError:
    normalized_code = (provider_code or "").lower()
    if status_code in {401, 403}:
        code = AiErrorCode.AUTHENTICATION_FAILED
    elif status_code == 402 or (
        status_code == 429 and any(word in normalized_code for word in ("quota", "billing"))
    ):
        code = AiErrorCode.INSUFFICIENT_QUOTA
    elif status_code == 429:
        code = AiErrorCode.RATE_LIMITED
    elif status_code == 404:
        code = AiErrorCode.MODEL_UNAVAILABLE
    elif status_code in {400, 413, 422}:
        code = AiErrorCode.INVALID_REQUEST
    elif status_code == 408:
        code = AiErrorCode.TIMEOUT
    else:
        code = AiErrorCode.PROVIDER_ERROR
    return AiError(code, retryable=status_code in {408, 409, 429} or status_code >= 500)
