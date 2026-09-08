import pytest

from app.modules.tasks.ai_lock import AiLockUnavailableError, MemberAiCallBusyError
from app.modules.tasks.ai_operations import TaskAiExecutionError
from app.modules.tasks.router import TaskApiError, _execute_ai


async def raising(error: Exception):
    raise error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "status"),
    [
        (MemberAiCallBusyError(), "ai_call_in_progress", 409),
        (AiLockUnavailableError(), "ai_lock_unavailable", 503),
        (
            TaskAiExecutionError(
                "provider_rate_limited",
                "Please retry",
                429,
                details={"retryable": True},
            ),
            "provider_rate_limited",
            429,
        ),
    ],
)
async def test_ai_errors_map_to_stable_api_errors(error, code, status) -> None:
    with pytest.raises(TaskApiError) as caught:
        await _execute_ai(raising(error))
    assert caught.value.code == code
    assert caught.value.status_code == status


@pytest.mark.asyncio
async def test_execution_error_preserves_only_explicit_safe_details() -> None:
    error = TaskAiExecutionError(
        "provider_error",
        "Safe message",
        502,
        details={"operation_id": "known-id"},
    )
    with pytest.raises(TaskApiError) as caught:
        await _execute_ai(raising(error))
    assert caught.value.details == {"operation_id": "known-id"}
