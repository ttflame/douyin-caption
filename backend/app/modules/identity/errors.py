from fastapi import Request
from fastapi.responses import JSONResponse


class IdentityError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def not_found(resource: str) -> IdentityError:
    return IdentityError(
        f"{resource}_not_found",
        f"{resource.replace('_', ' ').title()} not found",
        404,
    )


async def identity_exception_handler(_: Request, exc: IdentityError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
