import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.request_trace import request_trace_middleware
from app.modules.telemetry.router import ClientEventSubmit


async def test_request_id_is_reused_when_valid_and_replaced_when_invalid() -> None:
    app = FastAPI()
    app.middleware("http")(request_trace_middleware)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/probe", headers={"X-Request-ID": "logical-123"})
        assert response.headers["X-Request-ID"] == "logical-123"
        response = await client.get("/probe", headers={"X-Request-ID": "invalid request id"})
        assert response.headers["X-Request-ID"] != "invalid request id"


def test_client_event_schema_rejects_content_and_credentials() -> None:
    base = {
        "event_type": "api_timeout",
        "stage": "first_draft_submit",
        "route": "/workbench/task",
        "browser": "chromium",
        "platform": "android",
        "viewport": "390x844",
        "online": True,
        "visibility": "visible",
    }
    ClientEventSubmit.model_validate(base)
    with pytest.raises(ValidationError):
        ClientEventSubmit.model_validate({**base, "request_body": "private content"})
    with pytest.raises(ValidationError):
        ClientEventSubmit.model_validate({**base, "authorization": "Bearer secret"})
