"""run 执行：驱动 Agent 事件流、维护工作区/租约，并在收尾时结算。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ag_ui.core import RunErrorEvent
from pydantic_ai import CancellationToken, DeferredToolResults
from pydantic_ai.toolsets import AbstractToolset

from app.agents.protocol.errors import summarize_error
from app.agents.runtime.base import BaseAgent
from app.agents.tools.bundle import build_tool_bundle
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, StorageUnavailableError, UnprocessableError
from app.db.session import SessionFactory
from app.enums import RunStatus
from app.infra.files.storage import ObjectStorage, get_storage
from app.infra.providers.llm import ResolvedModel
from app.render.producer import RenderProducer
from app.sandbox.pool import SandboxPool
from app.sandbox.workspace import (
    LocalWorkspace,
    RunWorkspace,
    SandboxWorkspace,
    can_use_sandbox,
)
from app.services.billing import credit_guard
from app.services.billing import service as billing
from app.services.chat import log as chat_log
from app.services.model import image as image_model_service
from app.services.run.lease import RUN_LEASE_SECONDS, finish_run, renew_run_lease
from app.services.run.options import _settings_with_thinking
from app.services.run.registry import RunRegistry
from app.services.run.store import set_run_status
from app.services.run.tree import get_run_or_404

logger = logging.getLogger(__name__)


async def execute_run(
    *,
    producer: RenderProducer,
    session_factory: SessionFactory,
    session_id: UUID,
    run_id: str,
    owner_id: UUID,
    resolved: ResolvedModel,
    model_id: int | None,
    thinking_level: str | None = None,
    cancellation_token: CancellationToken | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    registry: RunRegistry | None = None,
    toolset: AbstractToolset[Any] | None = None,
    enable_web_search: bool = False,
    enable_image_generation: bool = True,
    image_model_id: int | None = None,
    sandbox_pool: SandboxPool | None = None,
    settings: Settings | None = None,
) -> None:
    runtime = settings or get_settings()
    run_uuid = UUID(run_id)
    workspace: RunWorkspace | None = None
    error: str | None = None
    started_at = time.perf_counter()
    wall_started = datetime.now(UTC)
    has_logged_first_event = False
    # 租约心跳：长工具调用期间不写 item，心跳保住租约，别的 resume 才抢不走
    heartbeat = asyncio.create_task(
        _renew_lease_loop(session_factory, session_id, run_id, registry, producer)
    )
    try:
        # 不支持工具的模型不需要工作区，避免白白建目录 / 启沙箱
        workspace = (
            await _build_workspace(session_id, run_id, sandbox_pool, runtime)
            if resolved.supports_tools
            else None
        )
        logger.info(
            "Run %s workspace prepared in %.2fs (sandbox=%s)",
            run_id,
            time.perf_counter() - started_at,
            isinstance(workspace, SandboxWorkspace),
        )
        # 有可用的图片模型、平台开着、本次也开着，才把生成工具挂上去
        image_model_id = await _resolve_image_model_id(
            session_factory,
            image_model_id,
            enabled=(
                resolved.supports_tools
                and enable_image_generation
                and runtime.feature_image_generation_enabled
            ),
        )
        bundle = build_tool_bundle(
            resolved.model,
            workspace=workspace,
            session_factory=session_factory,
            owner_id=owner_id,
            settings=runtime,
            run_id=run_uuid,
            image_model_id=image_model_id,
            enable_image_generation=image_model_id is not None,
            enable_web_search=enable_web_search,
            offer_workspace_tools=resolved.supports_tools,
        )
        model_settings = _settings_with_thinking(resolved.settings, thinking_level)

        # 用量落库后按水位差结算，余额见底就停掉本轮；策略本体在 credit_guard
        usage_guard = credit_guard.make_usage_guard(
            session_factory,
            runtime,
            session_id=session_id,
            run_id=run_uuid,
            owner_id=owner_id,
        )

        agent = BaseAgent(
            resolved.model,
            model_settings=model_settings,
            session_id=session_id,
            model_id=model_id,
            session_factory=session_factory,
            run_id=run_id,
            tools=bundle.tools,
            prompt=bundle.instructions,
            context_window=resolved.context_window,
            compaction_threshold=(
                resolved.compaction_threshold
                if resolved.compaction_threshold is not None
                else runtime.compaction_threshold
            ),
            supports_tools=resolved.supports_tools,
            on_usage=usage_guard,
        )
        # 用户消息已经在 start_run_turn 里写入，agent 只从 message_history 读
        async for event in agent.agui_events(
            None,
            run_id=run_id,
            deferred_tool_results=deferred_tool_results,
            cancellation_token=cancellation_token,
            toolsets=([toolset] if toolset is not None and resolved.supports_tools else None),
        ):
            if not has_logged_first_event:
                has_logged_first_event = True
                logger.info(
                    "Run %s first stream event after %.2fs",
                    run_id,
                    time.perf_counter() - started_at,
                )
            await producer.publish(event)
    except asyncio.CancelledError:
        # 取消时未回填的 tool call 留在原地，用户可以再 resume 那条分支
        error = "run cancelled"
        raise
    except Exception as exc:
        summary = summarize_error(exc)
        error = summary.message
        logger.exception("Run %s failed in session %s", run_id, session_id)
        with contextlib.suppress(Exception):
            async with session_factory() as db:
                await set_run_status(db, session_id, UUID(run_id), RunStatus.FAILED)
        with contextlib.suppress(Exception):
            await producer.publish(RunErrorEvent(message=error, code=summary.code))
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        if registry is not None:
            await registry.unregister(run_id)
        final_status = await _final_status(session_factory, session_id, run_uuid)
        await _shutdown_workspace(
            workspace,
            sandbox_pool,
            session_id=session_id,
            run_id=run_uuid,
            final_status=final_status,
        )
        await _release_run_lease(session_factory, session_id, run_id)
        await _settle_and_log(
            session_factory,
            settings=runtime,
            session_id=session_id,
            run_id=run_uuid,
            final_status=final_status,
            error=error,
            started_at=wall_started,
        )
        await producer.close()


async def _settle_and_log(
    session_factory: SessionFactory,
    *,
    settings: Settings,
    session_id: UUID,
    run_id: UUID,
    final_status: RunStatus | None,
    error: str | None,
    started_at: datetime,
) -> None:
    """收尾最后一步：结算积分，并留一条请求日志。

    记账和日志各自吞异常——它们失败不该影响 run 的收尾结果，用量已经在库里，
    下次结算（或人工对账）补得上。
    """
    try:
        async with session_factory() as db:
            # 日志里的扣分从流水汇总（实时结算也算），这里只负责兜最后一批差额
            await billing.settle_run(db, settings, session_id=session_id, run_id=run_id)
            await chat_log.finish_run_log(
                db,
                session_id=session_id,
                run_id=run_id,
                status=final_status.value if final_status is not None else None,
                error=error,
                started_at=started_at,
            )
    except Exception:
        logger.exception("Billing settlement failed for run %s", run_id)


async def _build_workspace(
    session_id: UUID,
    run_id: str,
    pool: SandboxPool | None,
    settings: Settings,
) -> RunWorkspace:
    """配好沙箱且平台总闸开着 → 云端工作区；否则本地临时目录。"""
    storage: ObjectStorage | None
    try:
        storage = get_storage()
    except StorageUnavailableError:
        # 本地工作区不依赖对象存储也能读写；只有 load_files 才需要它
        storage = None
    if can_use_sandbox(settings):
        if storage is None:
            raise UnprocessableError("沙箱工作区需要对象存储（S3_BUCKET）")
        if pool is None:
            raise UnprocessableError("沙箱未在应用里启用（app.state 缺 sandbox_pool）")
        pool.configure(settings)
        # 沙箱按需启动：先返回工作区，等模型第一次调用沙箱工具时再向 pool 要容器。
        return SandboxWorkspace(
            storage,
            session_id,
            run_id,
            sandbox_factory=lambda: pool.acquire(session_id, run_id),
            on_activity=lambda: pool.touch(session_id),
        )

    return LocalWorkspace(settings, storage, session_id, run_id)


async def _resolve_image_model_id(
    session_factory: SessionFactory,
    image_model_id: int | None,
    *,
    enabled: bool,
) -> int | None:
    """图片工具开跑前定一次模型：默认模型也在这里落到具体 id。"""
    if not enabled:
        return None
    async with session_factory() as db:
        model = await image_model_service.get_active_model(db, image_model_id)
        return model.id if model is not None else None


async def _final_status(
    session_factory: SessionFactory, session_id: UUID, run_id: UUID
) -> RunStatus | None:
    """run 的终态；run 已被并发删除就当没有，其余读库失败必须留痕。"""
    try:
        async with session_factory() as db:
            run = await get_run_or_404(db, session_id, run_id)
            return RunStatus(run.status)
    except NotFoundError:
        return None
    except Exception:
        logger.exception("Failed to read final status of run %s in session %s", run_id, session_id)
        return None


async def _shutdown_workspace(
    workspace: RunWorkspace | None,
    pool: SandboxPool | None,
    *,
    session_id: UUID,
    run_id: UUID,
    final_status: RunStatus | None,
) -> None:
    """收尾两件事：工作区清退、沙箱按回收策略 pause/kill；产物由 publish_file 负责。"""
    if workspace is None:
        return
    started_at = time.perf_counter()
    with contextlib.suppress(Exception):
        await workspace.cleanup()
    if pool is not None:
        try:
            if final_status in (RunStatus.INTERRUPTED, RunStatus.COMPLETED):
                # 正常结束和等待 resume 只归还使用权；挂起由空闲巡检异步做
                await pool.release(session_id)
            else:
                await pool.discard(session_id)
        except Exception:
            logger.exception("Sandbox shutdown failed for run %s", run_id)
    logger.info("Run %s workspace released in %.2fs", run_id, time.perf_counter() - started_at)


async def _renew_lease_loop(
    session_factory: SessionFactory,
    session_id: UUID,
    run_id: str,
    registry: RunRegistry | None = None,
    producer: RenderProducer | None = None,
) -> None:
    """按租约三分之一周期续租，直到 finally 把它取消掉。

    单次续租失败只记日志、不退出：数据库抖一下就该继续试，
    真的一直续不上则由租约到期 + 启动清扫兜底。
    """
    interval = RUN_LEASE_SECONDS / 3
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                await renew_run_lease(db, session_id, run_id)
            if registry is not None:
                await registry.touch(run_id)
            if producer is not None:
                await producer.touch()
        except Exception:
            logger.exception("Lease renewal failed for run %s in session %s", run_id, session_id)


async def _release_run_lease(
    session_factory: SessionFactory, session_id: UUID, run_id: str
) -> None:
    try:
        async with session_factory() as db:
            await finish_run(db, session_id, run_id)
    except Exception:
        # 清不掉会让前端一直以为 run 还在；租约到期后启动清扫会兜底
        logger.exception("Failed to release run lease %s in session %s", run_id, session_id)
