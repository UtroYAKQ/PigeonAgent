import uuid
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.config import Settings, get_settings
from app.core.exceptions import UnauthenticatedError
from app.db import get_db, get_session_factory
from app.models.user import User
from app.render import RenderHub
from app.services.run import RunRegistry
from app.services.sandbox_pool import SandboxPool

SessionDep = Annotated[AsyncSession, Depends(get_db)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False：缺头时我们自己抛 401，报错文案统一走 UnauthenticatedError
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthenticatedError("需要登录")
    user_id = security.decode_token(
        credentials.credentials, security.ACCESS, secret_key=settings.secret_key
    )
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise UnauthenticatedError("登录状态无效或已过期")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_user_optional(
    db: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    """带合法 token 就解析出用户，没有就放行匿名。

    整个 API 还处在逐步接入鉴权的过渡期，files 这类接口用可选用户：
    有 token 严格执行归属校验，没有 token 保持现状（匿名上传 + 公开下载）。
    """
    if credentials is None:
        return None
    try:
        user_id = security.decode_token(
            credentials.credentials, security.ACCESS, secret_key=settings.secret_key
        )
    except Exception:
        return None
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        return None
    return user


OptionalUserDep = Annotated[User | None, Depends(get_current_user_optional)]


def get_sandbox_pool(request: Request) -> SandboxPool | None:
    """没配 SANDBOX_API_KEY 时 lifespan 不会建池，这里补成 None 走本地模式。"""
    pool = getattr(request.app.state, "sandbox_pool", None)
    if pool is None:
        return None
    return cast(SandboxPool, pool)


SandboxPoolDep = Annotated[SandboxPool | None, Depends(get_sandbox_pool)]


def get_render_hub(request: Request) -> RenderHub:
    return cast(RenderHub, request.app.state.render_hub)


def get_run_registry(request: Request) -> RunRegistry:
    return cast(RunRegistry, request.app.state.run_registry)


RenderHubDep = Annotated[RenderHub, Depends(get_render_hub)]
RunRegistryDep = Annotated[RunRegistry, Depends(get_run_registry)]
