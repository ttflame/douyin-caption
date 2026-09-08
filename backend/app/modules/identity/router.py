from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.provider_url import ProviderUrlPolicy
from app.modules.identity.errors import IdentityError
from app.modules.identity.models import Member
from app.modules.identity.provider import OpenAICompatibleConnectionTester
from app.modules.identity.rate_limit import (
    InMemoryLoginRateLimiter,
    LoginAttemptLimiter,
    LoginRateLimiter,
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
)
from app.modules.identity.repositories import SqlAlchemyIdentityRepository
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MemberCreate,
    MemberPublic,
    MemberUpdate,
    MessageResponse,
    ProviderConnectionTestRequest,
    ProviderConnectionTestResult,
    ProviderSettingPublic,
    ProviderSettingWrite,
    ProviderTimeoutWrite,
)
from app.modules.identity.security import ApiKeyCipher, JwtService, PasswordService
from app.modules.identity.services import IdentityService

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
_in_memory_login_rate_limiter = InMemoryLoginRateLimiter()


def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IdentityService:
    return IdentityService(
        SqlAlchemyIdentityRepository(session),
        PasswordService(),
        JwtService(settings.app_secret_key),
        ApiKeyCipher(settings.key_encryption_secret),
        OpenAICompatibleConnectionTester(),
        ProviderUrlPolicy(production=settings.app_env.casefold() == "production"),
    )


async def get_login_rate_limiter() -> AsyncIterator[LoginAttemptLimiter]:
    settings = get_settings()
    if settings.allow_in_memory_coordination:
        yield _in_memory_login_rate_limiter
        return
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield LoginRateLimiter(client)
    finally:
        await client.aclose()


async def get_current_member(
    token: Annotated[str, Depends(oauth2_scheme)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> Member:
    return await service.authenticated_member(token)


async def get_current_admin(member: Annotated[Member, Depends(get_current_member)]) -> Member:
    IdentityService.require_admin(member)
    return member


@router.post("/auth/login", response_model=LoginResponse, tags=["authentication"])
async def login(
    request: Request,
    data: LoginRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
    rate_limiter: Annotated[LoginAttemptLimiter, Depends(get_login_rate_limiter)],
):
    client_ip = request.client.host if request.client is not None else "unknown"
    try:
        await rate_limiter.check(client_ip, data.username)
    except LoginRateLimitExceeded as exc:
        raise IdentityError(
            "login_rate_limited",
            "Too many login attempts; try again later",
            429,
            details={"retry_after": exc.retry_after},
        ) from exc
    except LoginRateLimitUnavailable as exc:
        raise IdentityError(
            "login_rate_limit_unavailable",
            "Login is temporarily unavailable",
            503,
        ) from exc
    token, member = await service.authenticate(data.username.strip(), data.password)
    return LoginResponse(access_token=token, member=MemberPublic.model_validate(member))


@router.get("/auth/me", response_model=MemberPublic, tags=["authentication"])
async def me(member: Annotated[Member, Depends(get_current_member)]):
    return member


@router.post("/auth/change-password", response_model=MessageResponse, tags=["authentication"])
async def change_password(
    data: ChangePasswordRequest,
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    await service.change_password(member, data.current_password, data.new_password)
    return MessageResponse(message="Password changed")


@router.get("/admin/members", response_model=list[MemberPublic], tags=["administration"])
async def list_members(
    admin: Annotated[Member, Depends(get_current_admin)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.repository.list_members()


@router.post("/admin/members", response_model=MemberPublic, tags=["administration"])
async def create_member(
    data: MemberCreate,
    admin: Annotated[Member, Depends(get_current_admin)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.create_member(admin, data)


@router.patch("/admin/members/{member_id}", response_model=MemberPublic, tags=["administration"])
async def update_member(
    member_id: UUID,
    data: MemberUpdate,
    admin: Annotated[Member, Depends(get_current_admin)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.update_member(admin, member_id, data)


@router.get("/settings/provider", response_model=ProviderSettingPublic, tags=["settings"])
async def get_provider_setting(
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.get_provider_setting(member)


@router.put("/settings/provider", response_model=ProviderSettingPublic, tags=["settings"])
async def put_provider_setting(
    data: ProviderSettingWrite,
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.put_provider_setting(member, data)


@router.patch("/settings/provider", response_model=ProviderSettingPublic, tags=["settings"])
async def patch_provider_timeout(
    data: ProviderTimeoutWrite,
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.patch_provider_timeout(member, data)


@router.delete("/settings/provider", response_model=MessageResponse, tags=["settings"])
async def delete_provider_setting(
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    await service.delete_provider_setting(member)
    return MessageResponse(message="Provider settings deleted")


@router.post(
    "/settings/provider/test", response_model=ProviderConnectionTestResult, tags=["settings"]
)
async def test_provider_setting(
    data: ProviderConnectionTestRequest,
    member: Annotated[Member, Depends(get_current_member)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
):
    return await service.test_provider(member, data)
