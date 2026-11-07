from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthenticatedError
from app.core.ids import parse_uuid
from app.core.rate_limit import RateLimiter
from app.db import get_db, get_session_factory
from app.models.user import User
from app.render import RenderHub
from app.sandbox.pool import SandboxPool
from app.services import app_config as config_service
from app.services.run.registry import RunRegistry
from app.tasks.operation_log import OperationLogger

SessionDep = Annotated[AsyncSession, Depends(get_db)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
EnvSettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_runtime_settings(db: SessionDep, settings: EnvSettingsDep) -> Settings:
    """环境变量打底、数据库覆盖：接口拿到的是真正生效的配置。"""
    return await config_service.resolve_settings(db, settings)


SettingsDep = Annotated[Settings, Depends(get_runtime_settings)]

# auto_error=False：缺头时我们自己抛 401，报错文案统一走 UnauthenticatedError
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    db: SessionDep,
    settings: EnvSettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthenticatedError("需要登录")
    user_id, token_version = security.decode_token(
        credentials.credentials, security.ACCESS, secret_key=settings.secret_key
    )
    parsed_id = parse_uuid(user_id)
    if parsed_id is None:
        raise UnauthenticatedError("登录状态无效或已过期")
    user = await db.get(User, parsed_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise UnauthenticatedError("登录状态无效或已过期")
    request.state.operation_actor_id = user.id
    request.state.operation_actor_email = user.email
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUserDep) -> User:
    """写操作的身份闸门：模型这类全局资源只允许管理员改。"""
    if not user.is_admin:
        raise ForbiddenError("需要管理员权限")
    return user


AdminUserDep = Annotated[User, Depends(get_current_admin)]


def get_sandbox_pool(request: Request) -> SandboxPool | None:
    """lifespan 常驻一个池；测试或未跑 lifespan 时返回 None，走本地模式。"""
    pool = getattr(request.app.state, "sandbox_pool", None)
    if pool is None:
        return None
    return cast(SandboxPool, pool)


SandboxPoolDep = Annotated[SandboxPool | None, Depends(get_sandbox_pool)]


def get_render_hub(request: Request) -> RenderHub:
    return cast(RenderHub, request.app.state.render_hub)


def get_run_registry(request: Request) -> RunRegistry:
    return cast(RunRegistry, request.app.state.run_registry)


def get_rate_limiter(request: Request) -> RateLimiter:
    return cast(RateLimiter, request.app.state.rate_limiter)


def get_operation_logger(request: Request) -> OperationLogger | None:
    """lifespan 之外（测试、未启动）没有日志器；刷队列的动作按可选处理。"""
    logger = getattr(request.app.state, "operation_logger", None)
    if logger is None:
        return None
    return cast(OperationLogger, logger)


RenderHubDep = Annotated[RenderHub, Depends(get_render_hub)]
RunRegistryDep = Annotated[RunRegistry, Depends(get_run_registry)]
OperationLoggerDep = Annotated[OperationLogger | None, Depends(get_operation_logger)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
