"""后台运行编排：开轮占位、把 Agent 事件接到 render 队列、维护 session 的 active run。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from ag_ui.core import RunErrorEvent
from pydantic_ai import CancellationToken, DeferredToolResults, ModelSettings, Tool
from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.tools import frontend_toolset, web_search_tools, workspace_instructions
from app.agents.tools.workspace import workspace_tools
from app.agents.turn import summarize_error
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, StorageUnavailableError, UnprocessableError
from app.db.session import SessionFactory
from app.domain.run_items import ResourceItem, RunItem
from app.enums import RunStatus
from app.infra.model_factory import ModelFactory, ResolvedModel
from app.infra.storage import ObjectStorage, get_storage
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.render.hub import RenderHub
from app.render.producer import RenderProducer
from app.sandbox.pool import SandboxPool
from app.sandbox.workspace import (
    LocalWorkspace,
    RunWorkspace,
    SandboxWorkspace,
    sandbox_enabled,
)
from app.schemas.run import RunCreate, RunResume
from app.services import billing, chat_log, credit_guard, file_service, run_store
from app.services import chat_session as session_service
from app.services import image_model as image_model_service
from app.services.run_store import RUN_LEASE_SECONDS, ResumeDecisions

logger = logging.getLogger(__name__)


@dataclass
class RunRegistry:
    """运行任务与取消令牌的注册表；随 app.state 生命周期存在。"""

    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    cancellations: dict[str, tuple[UUID, CancellationToken]] = field(default_factory=dict)

    def schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def cancel_run(self, session_id: UUID, run_id: str, hub: RenderHub) -> None:
        cancellation = self.cancellations.get(run_id)
        if cancellation is not None and cancellation[0] != session_id:
            raise NotFoundError(f"Run {run_id} is not active")
        if hub.distributed:
            await hub.request_cancel(session_id, run_id)
        elif cancellation is None:
            raise NotFoundError(f"Run {run_id} is not active")
        if cancellation is not None:
            cancellation[1].cancel()

    async def cancel_all(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def launch_run(
    db: AsyncSession,
    session_id: UUID,
    payload: RunCreate | RunResume,
    *,
    owner_id: UUID,
    session_factory: SessionFactory,
    hub: RenderHub,
    registry: RunRegistry,
    sandbox_pool: SandboxPool | None = None,
    settings: Settings | None = None,
) -> str:
    runtime = settings or get_settings()
    resource_items: list[RunItem] = []
    if isinstance(payload, RunResume):
        user_input = None
        attachments = []
        retry_run_id = parent_run_id = None
        parent_was_given = False
        deferred_tool_results = DeferredToolResults(
            approvals=dict(payload.approvals), calls=dict(payload.calls)
        )
        resume = ResumeDecisions(
            interrupt_id=payload.interrupt_id,
            approvals=dict(payload.approvals),
            calls=dict(payload.calls),
        )
    else:
        user_input = payload.input
        # file_id 附件当场核归属并归一化，别把客户端自报的 kind/mime 直接喂给模型
        attachments = await file_service.resolve_attachments(
            db, payload.attachments, owner=owner_id
        )
        # 引用的文件当场核对， ResourceItem 里带上官方记录的名字与大小
        resource_items = await file_service.resource_items_for(
            db, payload.resources, owner=owner_id
        )
        retry_run_id = payload.retry_run_id
        parent_run_id = payload.parent_run_id
        parent_was_given = payload.parent_was_given
        deferred_tool_results = None
        resume = None

    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=owner_id)
    resolved_model_id = payload.model_id if payload.model_id is not None else chat_session.model_id
    if resolved_model_id is None:
        raise UnprocessableError(
            "Session has no model_id; set one on the session or in the request"
        )
    record = await db.get(LlmModel, resolved_model_id)
    if record is None:
        raise UnprocessableError(f"Model {resolved_model_id} not found")
    resolved = ModelFactory().create(record)
    thinking_level = _supported_thinking_level(record, chat_session.thinking_level)
    toolset = frontend_toolset(payload.tools)
    # 平台总闸优先：关掉之后，客户端即使传了 true 也不下发工具
    enable_web_search = payload.enable_web_search and runtime.feature_web_search_enabled
    enable_image_generation = (
        payload.enable_image_generation and runtime.feature_image_generation_enabled
    )
    image_model_id = payload.image_model_id if enable_image_generation else None
    # 明确选了一个不可用的模型时当场拒掉；后台再发现就没法给请求返回 422 了
    if (
        image_model_id is not None
        and await image_model_service.get_active_model(db, image_model_id) is None
    ):
        raise UnprocessableError("所选图片模型不可用，请重新选择")
    if not resolved.supports_tools:
        if isinstance(payload, RunResume):
            raise UnprocessableError(
                "当前模型不支持工具调用，无法恢复待审批/外部调用；请先切换到支持工具的模型"
            )
        if enable_web_search or resource_items:
            raise UnprocessableError(
                f"模型「{record.name}」未开启工具调用支持，无法使用联网搜索或文件工作区"
            )
        # 浏览器工具声明是每轮固定下发的，非工具模型直接忽略即可
        toolset = None
    if enable_web_search and not runtime.deepseek_api_key:
        raise UnprocessableError("联网搜索未配置：请在配置项里填写 DeepSeek API Key")
    # 积分不足就在开跑前拦下：跑完再告知"你欠费了"是最糟的体验
    await billing.require_credits(db, runtime, owner_id)

    # 生成 run id；session.active_run_id 由 start_run_turn 在同一事务里占用
    run_id = str(uuid4())
    producer = await hub.create(session_id, run_id)
    try:
        await run_store.start_run_turn(
            db,
            session_id,
            run_id=run_id,
            user_input=user_input,
            attachments=attachments,
            resource_items=list(resource_items) if not resume else [],
            retry_run_id=retry_run_id,
            parent_run_id=parent_run_id,
            parent_was_given=parent_was_given,
            resume=resume,
            model_id=resolved_model_id,
        )
    except Exception:
        await producer.close()
        raise

    cancellation_token = CancellationToken()
    registry.cancellations[run_id] = (session_id, cancellation_token)
    registry.schedule(
        execute_run(
            producer=producer,
            session_factory=session_factory,
            session_id=session_id,
            run_id=run_id,
            deferred_tool_results=deferred_tool_results,
            resolved=resolved,
            model_id=resolved_model_id,
            thinking_level=thinking_level,
            cancellation_token=cancellation_token,
            registry=registry,
            hub=hub,
            toolset=toolset,
            enable_web_search=enable_web_search,
            enable_image_generation=enable_image_generation,
            image_model_id=image_model_id,
            sandbox_pool=sandbox_pool,
            settings=runtime,
        )
    )
    return run_id


async def execute_run(
    *,
    producer: RenderProducer,
    session_factory: SessionFactory,
    session_id: UUID,
    run_id: str,
    resolved: ResolvedModel,
    model_id: int | None,
    thinking_level: str | None = None,
    cancellation_token: CancellationToken | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    registry: RunRegistry | None = None,
    hub: RenderHub | None = None,
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
    first_event_logged = False
    # 租约心跳：长工具调用期间不写 item，心跳保住租约，别的 resume 才抢不走
    heartbeat = asyncio.create_task(_renew_lease_loop(session_factory, session_id, run_id, hub=hub))
    cancellation_watcher = (
        asyncio.create_task(_watch_cancellation(hub, session_id, run_id, cancellation_token))
        if hub is not None and hub.distributed and cancellation_token is not None
        else None
    )
    try:
        async with session_factory() as db:
            # 不支持工具的模型不需要工作区，避免白白建目录 / 启沙箱
            workspace = (
                await _build_workspace(db, session_id, run_id, sandbox_pool, runtime)
                if resolved.supports_tools
                else None
            )
            logger.info(
                "Run %s workspace prepared in %.2fs (sandbox=%s)",
                run_id,
                time.perf_counter() - started_at,
                isinstance(workspace, SandboxWorkspace),
            )
            # 本地模式没有注入资源时不开文件工具：纯聊天省事，TestModel 之类的
            # 顺序调用模型也不会被无关工具干扰；沙箱模式始终带着命令执行。
            run_obj = await run_store.get_run_or_404(db, session_id, run_uuid)
            offer_tools = resolved.supports_tools and (
                isinstance(workspace, SandboxWorkspace)
                or any(isinstance(item, ResourceItem) for item in run_obj.content)
            )
            wtools: list[Tool[Any]] = []
            session_owner = await _session_owner(session_factory, session_id)
            if offer_tools and workspace is not None:
                wtools = workspace_tools(
                    workspace,
                    session_factory,
                    owner_id=session_owner,
                    settings=runtime,
                )
            # 有可用的图片模型、平台开着、本次也开着，才把生成工具挂上去
            image_model = None
            image_ready = (
                resolved.supports_tools
                and enable_image_generation
                and runtime.feature_image_generation_enabled
            )
            if image_ready:
                image_model = await image_model_service.get_active_model(db, image_model_id)
                image_ready = image_model is not None
            search_tools = web_search_tools(runtime) if enable_web_search else []
            model_settings = _settings_with_thinking(resolved.settings, thinking_level)

            # 用量落库后按水位差结算，余额见底就停掉本轮；策略本体在 credit_guard
            usage_guard = credit_guard.make_usage_guard(
                session_factory,
                runtime,
                session_id=session_id,
                run_id=run_uuid,
                owner_id=session_owner,
            )

            agent = BaseAgent(
                resolved.model,
                model_settings=model_settings,
                db=db,
                session_id=session_id,
                model_id=model_id,
                session_factory=session_factory,
                run_id=run_id,
                tools=[*wtools, *search_tools],
                prompt=workspace_instructions() if wtools else None,
                context_window=resolved.context_window,
                compaction_threshold=(
                    resolved.compaction_threshold
                    if resolved.compaction_threshold is not None
                    else runtime.compaction_threshold
                ),
                supports_tools=resolved.supports_tools,
                owner_id=session_owner,
                enable_image_generation=image_ready,
                image_model_id=image_model.id if image_model is not None else None,
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
                if not first_event_logged:
                    first_event_logged = True
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
                await run_store.set_run_status(db, session_id, UUID(run_id), RunStatus.FAILED)
        with contextlib.suppress(Exception):
            await producer.publish(RunErrorEvent(message=error, code=summary.code))
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        if cancellation_watcher is not None:
            cancellation_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancellation_watcher
        if registry is not None:
            registry.cancellations.pop(run_id, None)
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
    db: AsyncSession,
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
    if sandbox_enabled(settings):
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


async def _session_owner(session_factory: SessionFactory, session_id: UUID) -> UUID | None:
    """产物归属跟会话主人走；查不到（会话被并发删了）就按匿名处理。

    读库失败同样按匿名走，但必须留痕：余额熔断依赖这个 owner，静默失败等于免检。
    """
    try:
        async with session_factory() as db:
            value = await db.scalar(
                select(ChatSession.owner_id).where(ChatSession.id == session_id)
            )
            return value
    except Exception:
        logger.exception("Failed to resolve owner of session %s", session_id)
        return None


def _supported_thinking_level(record: LlmModel, level: str | None) -> str | None:
    if level is None or level not in record.thinking_levels:
        return None
    return level


def _settings_with_thinking(settings: ModelSettings, thinking_level: str | None) -> ModelSettings:
    if thinking_level is None:
        return settings
    return cast(ModelSettings, {**settings, "thinking": thinking_level})


async def _final_status(
    session_factory: SessionFactory, session_id: UUID, run_id: UUID
) -> RunStatus | None:
    """run 的终态；run 已被并发删除就当没有，其余读库失败必须留痕。"""
    try:
        async with session_factory() as db:
            run = await run_store.get_run_or_404(db, session_id, run_id)
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
    with contextlib.suppress(Exception):
        await workspace.cleanup()
    if pool is not None:
        try:
            if final_status in (RunStatus.INTERRUPTED, RunStatus.COMPLETED):
                # 正常结束和等待 resume 都挂起保活：同一会话的下一轮直接复用
                await pool.release(session_id)
            else:
                await pool.discard(session_id)
        except Exception:
            logger.exception("Sandbox shutdown failed for run %s", run_id)


async def _renew_lease_loop(
    session_factory: SessionFactory,
    session_id: UUID,
    run_id: str,
    *,
    hub: RenderHub | None = None,
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
                await run_store.renew_run_lease(db, session_id, run_id)
            if hub is not None:
                await hub.renew(session_id, run_id)
        except Exception:
            logger.exception("Lease renewal failed for run %s in session %s", run_id, session_id)


async def _watch_cancellation(
    hub: RenderHub,
    session_id: UUID,
    run_id: str,
    cancellation_token: CancellationToken,
) -> None:
    """轮询持久取消键，避免 Pub/Sub 消息在 worker 重连时丢失。"""
    while True:
        if await hub.cancellation_requested(session_id, run_id):
            cancellation_token.cancel()
            return
        await asyncio.sleep(0.25)


async def _release_run_lease(
    session_factory: SessionFactory, session_id: UUID, run_id: str
) -> None:
    try:
        async with session_factory() as db:
            await run_store.finish_run(db, session_id, run_id)
    except Exception:
        # 清不掉会让前端一直以为 run 还在；租约到期后启动清扫会兜底
        logger.exception("Failed to release run lease %s in session %s", run_id, session_id)
