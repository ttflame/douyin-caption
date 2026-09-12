import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request, Response

logger = logging.getLogger("app.requests")
request_id_context: ContextVar[str] = ContextVar("request_id", default="")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


async def request_trace_middleware(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if _REQUEST_ID.fullmatch(supplied) else str(uuid4())
    attempt = request.headers.get("X-Request-Attempt", "1")[:3]
    request.state.request_id = request_id
    if request.url.path.endswith("/client-events") and int(
        request.headers.get("content-length", "0") or 0
    ) > 8_192:
        response = Response(status_code=413)
        response.headers["X-Request-ID"] = request_id
        return response
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        logger.info(
            "request completed request_id=%s attempt=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            attempt if attempt.isdigit() else "1",
            request.method,
            request.url.path,
            status,
            round((time.perf_counter() - started) * 1000),
        )
        request_id_context.reset(token)
