import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.session import async_session_factory, close_engine
from app.render.hub import RenderHub
from app.services import blob_gc
from app.services.run import RunRegistry
from app.services.sandbox_pool import SandboxPool
from app.services.session_run import clear_active_runs
from app.services.storage import get_storage
from app.services.user import ensure_admin

logger = logging.getLogger(__name__)


async def _sweep_stale_streams() -> None:
    try:
        async with async_session_factory() as session:
            # 单进程部署：刚启动时不存在本进程之外的活跃 run，全部清空
            await clear_active_runs(session)
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
    return asyncio.create_task(
        blob_gc.run_forever(async_session_factory, settings, get_storage())
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    sweep = asyncio.create_task(_sweep_stale_streams())
    seed = asyncio.create_task(_seed_admin())
    gc_sweep = asyncio.create_task(_blob_gc_sweep_once())
    gc_loop = _spawn_gc_task()
    sandbox_pool = _spawn_sandbox_pool(app)
    yield
    sweep.cancel()
    seed.cancel()
    gc_sweep.cancel()
    if gc_loop is not None:
        gc_loop.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sweep
        await seed
        await gc_sweep
        if gc_loop is not None:
            await gc_loop
    await app.state.run_registry.cancel_all()
    if sandbox_pool is not None:
        await sandbox_pool.aclose()
    await close_engine()


def _spawn_sandbox_pool(app: FastAPI) -> SandboxPool | None:
    """配了 SANDBOX_API_KEY 才启沙箱池；后台巡检负责空闲回收。"""
    settings = get_settings()
    if not settings.sandbox_api_key:
        app.state.sandbox_pool = None
        return None
    pool = SandboxPool(settings)
    pool.start()
    app.state.sandbox_pool = pool
    return pool


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.render_hub = RenderHub()
    app.state.run_registry = RunRegistry()
    app.add_exception_handler(AppError, app_error_handler)
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
