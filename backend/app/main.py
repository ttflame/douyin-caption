import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.identity.errors import IdentityError, identity_exception_handler
from app.modules.tasks.ai_worker import AiQueueWorker
from app.modules.tasks.router import TaskApiError, get_member_ai_call_lock, task_exception_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    lock_dependency = get_member_ai_call_lock()
    call_lock = await anext(lock_dependency)
    worker = AiQueueWorker(async_session_factory, call_lock)
    runner = asyncio.create_task(worker.run())
    app.state.ai_worker = worker
    try:
        yield
    finally:
        runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner
        await lock_dependency.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Douyin Caption API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")
    app.add_exception_handler(IdentityError, identity_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(TaskApiError, task_exception_handler)  # type: ignore[arg-type]

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
