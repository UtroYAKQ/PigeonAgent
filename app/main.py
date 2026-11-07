import asyncio
import contextlib
import hashlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import WEAK_ADMIN_PASSWORDS, Settings, get_settings
from app.core.exceptions import AppError, describe_error
from app.core.rate_limit import RateLimiter
from app.core.request_context import RequestContextMiddleware
from app.db.session import async_session_factory, close_engine
from app.infra.storage import get_storage
from app.render.hub import RenderHub
from app.sandbox.pool import SandboxPool
from app.services import app_config as config_service
from app.services.run.lease import clear_expired_run_leases
from app.services.run.registry import RunRegistry
from app.services.user import ensure_admin
from app.tasks import blob_gc
from app.tasks.operation_log import OperationLogger

logger = logging.getLogger(__name__)

_DATABASE_PROBE_TIMEOUT_SECONDS = 5


async def _check_database() -> bool:
    """启动前先探活数据库，失败时只输出一条清晰的降级提示，避免连环 traceback。"""
    try:
        async with asyncio.timeout(_DATABASE_PROBE_TIMEOUT_SECONDS):
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
    except Exception as exc:
        reason = describe_error(exc)
        logger.error(
            "\n"
            "============================================================\n"
            "  数据库连接失败，应用将以降级模式启动\n"
            "  影响：登录、会话、模型配置、操作日志等依赖数据库的功能不可用\n"
            "  原因：%s\n"
            "  处理：请确认 PostgreSQL 已启动，然后重启后端服务\n"
            "  配置：检查 .env 中的 DATABASE_URL\n"
            "============================================================",
            reason,
        )
        return False
    return True


async def _sweep_stale_streams(hub: RenderHub) -> None:
    try:
        async with async_session_factory() as session:
            expired = await clear_expired_run_leases(session)
        for session_id, run_id in expired:
            try:
                # 数据库租约已过期，顺手把 Redis 的 active/owner 标记也解除
                await hub.finish(session_id, run_id)
            except Exception:
                logger.exception("Failed to clear stale stream markers for run %s", run_id)
    except Exception:
        # 启动清扫不能因为数据库暂时不可用而阻断应用启动，但必须留痕排查
        logger.exception("Startup sweep of stale streaming entries failed")


async def _seed_admin() -> None:
    try:
        await ensure_admin(async_session_factory, get_settings())
    except Exception:
        logger.exception("Seeding default admin failed; login may be unavailable")


async def _blob_gc_sweep_once() -> None:
    try:
        async with async_session_factory() as session:
            await blob_gc.sweep(session, get_settings(), get_storage())
    except Exception:
        # 启动时对象存储不可用不该阻断应用，巡检下一轮再补
        logger.exception("Startup blob GC sweep failed")


def _spawn_gc_task() -> asyncio.Task[None] | None:
    settings = get_settings()
    if not settings.s3_bucket or settings.gc_interval_seconds <= 0:
        return None
    return asyncio.create_task(blob_gc.run_forever(async_session_factory, settings, get_storage()))


async def _load_runtime_settings() -> Settings:
    """启动时补齐配置行并载入数据库覆盖；数据库不可用就退回环境变量。"""
    base = get_settings()
    try:
        async with async_session_factory() as session:
            await config_service.seed_defaults(session, base)
            return await config_service.resolve_settings(session, base)
    except Exception:
        logger.exception("Loading application config from database failed; using environment")
        return base


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    startup_tasks: list[asyncio.Task[None]] = []
    if await _check_database():
        startup_tasks = [
            asyncio.create_task(_sweep_stale_streams(app.state.render_hub)),
            asyncio.create_task(_seed_admin()),
            asyncio.create_task(_blob_gc_sweep_once()),
        ]
        gc_loop = _spawn_gc_task()
        if gc_loop is not None:
            startup_tasks.append(gc_loop)
        runtime_settings = await _load_runtime_settings()
    else:
        runtime_settings = settings
    operation_logger = OperationLogger(async_session_factory, runtime_settings)
    operation_logger.start()
    app.state.operation_logger = operation_logger
    sandbox_pool = _start_sandbox_pool(app, runtime_settings)
    await app.state.run_registry.start()
    with contextlib.suppress(TimeoutError):
        # Redis 暂时不可用时不要让启动卡住；listener 会自己重连
        await app.state.run_registry.wait_ready(seconds=1.0)
    yield
    for task in startup_tasks:
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        for task in startup_tasks:
            await task
    await app.state.run_registry.aclose()
    await app.state.render_hub.aclose()
    await sandbox_pool.aclose()
    await operation_logger.aclose()
    await close_engine()


def _start_sandbox_pool(app: FastAPI, settings: Settings) -> SandboxPool:
    """沙箱池常驻：配置表里启用/停用 e2b 后，下一轮 run 就能生效。"""
    pool = SandboxPool(settings)
    pool.start()
    app.state.sandbox_pool = pool
    return pool


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # 注册在 AppError 上，框架只会递 AppError 进来；Starlette 的签名要求写 Exception，
    # 所以这里收窄一次，而不是用 assert（-O 运行会把 assert 整句去掉）。
    error = cast(AppError, exc)
    content: dict[str, Any] = {"detail": error.detail}
    content.update(error.extra)
    return JSONResponse(status_code=error.status_code, content=content)


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# 旧版 .env.example 的示例值只保留摘要用于检测，避免把退役密钥写进公开仓库
_EXAMPLE_SECRET_KEY_SHA256 = "154855e71911023ad930ed44f631dabda3ba4e9e151e5cf5149540f68094c939"


def _check_insecure_defaults(settings: Settings) -> None:
    if not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY 未配置，无法启动。请在 .env 中设置，生成方式：\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    if hashlib.sha256(settings.secret_key.encode()).hexdigest() == _EXAMPLE_SECRET_KEY_SHA256:
        raise RuntimeError(
            "SECRET_KEY 仍是旧版 .env.example 的示例值，无法启动。请生成并替换为自己的 Fernet key。"
        )
    if settings.admin_password in WEAK_ADMIN_PASSWORDS:
        logger.warning(
            "Using the default ADMIN_PASSWORD; change it in .env before exposing this service"
        )


def _build_render_hub(settings: Settings) -> RenderHub:
    """配了 REDIS_URL 就把事件队列放进 Redis（多 worker 共享），否则进程内实现。"""
    if settings.redis_url:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
        )
        return RenderHub(
            max_backlog=settings.render_queue_max_backlog,
            redis_client=client,
            retain_seconds=settings.render_retain_seconds,
        )
    return RenderHub(max_backlog=settings.render_queue_max_backlog)


def _build_rate_limiter(settings: Settings) -> RateLimiter:
    """配了 REDIS_URL 就把窗口计数放进 Redis，多 worker 限的是同一个额度。"""
    if settings.redis_url:
        from redis.asyncio import Redis

        return RateLimiter(
            redis_client=Redis.from_url(
                settings.redis_url, socket_connect_timeout=3, health_check_interval=30
            )
        )
    return RateLimiter()


def _build_run_registry(settings: Settings) -> RunRegistry:
    """配了 REDIS_URL 就启用跨 worker 取消总线；否则取消只在当前进程内有效。"""
    if settings.redis_url:
        from redis.asyncio import Redis

        from app.services.run_control import RunControl

        return RunRegistry(
            control=RunControl(
                # Pub/Sub 客户端不挂 health_check，避免心跳 PING 混进消息流
                Redis.from_url(settings.redis_url, socket_connect_timeout=3),
                owns_redis=True,
            )
        )
    return RunRegistry()


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()
    _check_insecure_defaults(settings)
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.render_hub = _build_render_hub(settings)
    app.state.run_registry = _build_run_registry(settings)
    app.state.rate_limiter = _build_rate_limiter(settings)
    app.state.operation_logger = None
    app.add_exception_handler(AppError, app_error_handler)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
