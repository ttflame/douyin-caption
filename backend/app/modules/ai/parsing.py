"""Strict conversion of provider text into workflow DTOs."""

from pydantic import BaseModel, ValidationError

from .errors import AiError, AiErrorCode


def parse_structured_output[StructuredDto: BaseModel](
    text: str, output_type: type[StructuredDto]
) -> StructuredDto:
    try:
        return output_type.model_validate_json(text)
    except (ValidationError, ValueError) as exc:
        raise AiError(AiErrorCode.INVALID_RESPONSE, retryable=True) from exc
