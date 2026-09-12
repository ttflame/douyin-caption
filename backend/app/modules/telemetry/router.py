import logging
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.models import Member
from app.modules.identity.router import get_current_member

router = APIRouter()
logger = logging.getLogger("app.client_events")
_events: dict[str, deque[datetime]] = defaultdict(deque)
_SECRET = re.compile(r"(?i)(bearer|api[_ -]?key|password)\s*[:=]?\s*\S+")


def _redact(value: str | None) -> str | None:
    return _SECRET.sub(r"\1 [redacted]", value) if value else value


class ClientEventSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "api_start", "api_success", "api_timeout", "api_network_error",
        "api_http_error", "auth_expired", "window_error", "unhandled_rejection",
    ]
    stage: str = Field(max_length=60)
    request_id: str | None = Field(default=None, max_length=80)
    attempt: int | None = Field(default=None, ge=1, le=3)
    method: str | None = Field(default=None, max_length=10)
    path: str | None = Field(default=None, max_length=200)
    duration_ms: int | None = Field(default=None, ge=0, le=300_000)
    status: int | None = Field(default=None, ge=0, le=599)
    code: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=200)
    script: str | None = Field(default=None, max_length=120)
    line: int | None = Field(default=None, ge=0)
    route: str = Field(max_length=200)
    browser: Literal["chromium", "edge", "firefox", "safari", "other"]
    platform: Literal["windows", "macos", "linux", "android", "ios", "other"]
    viewport: str = Field(pattern=r"^\d{1,5}x\d{1,5}$")
    online: bool
    visibility: Literal["hidden", "visible", "prerender", "unloaded"]


@router.post("/client-events", status_code=204, tags=["system"])
async def receive_client_event(
    payload: ClientEventSubmit,
    request: Request,
    member: Annotated[Member, Depends(get_current_member)],
) -> Response:
    if int(request.headers.get("content-length", "0") or 0) > 8_192:
        return Response(status_code=413)
    now = datetime.now(UTC)
    bucket = _events[str(member.id)]
    cutoff = now - timedelta(minutes=1)
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= 120:
        return Response(status_code=429)
    bucket.append(now)
    logger.info(
        "client event member_id=%s event=%s stage=%s request_id=%s attempt=%s "
        "method=%s path=%s status=%s duration_ms=%s route=%s browser=%s viewport=%s "
        "platform=%s online=%s visibility=%s code=%s message=%s script=%s line=%s",
        member.id,
        payload.event_type,
        payload.stage,
        payload.request_id,
        payload.attempt,
        payload.method,
        payload.path,
        payload.status,
        payload.duration_ms,
        payload.route,
        payload.browser,
        payload.viewport,
        payload.platform,
        payload.online,
        payload.visibility,
        payload.code,
        _redact(payload.message),
        payload.script,
        payload.line,
    )
    return Response(status_code=204)
