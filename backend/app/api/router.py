from fastapi import APIRouter

from app.modules.identity.router import router as identity_router
from app.modules.tasks.router import router as tasks_router
from app.modules.telemetry.router import router as telemetry_router

api_router = APIRouter()
api_router.include_router(identity_router)
api_router.include_router(tasks_router)
api_router.include_router(telemetry_router)
