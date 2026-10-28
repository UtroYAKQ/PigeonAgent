"""后台运行编排：开轮占位、把 Agent 事件接到 render 队列、维护 session 的 active run。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from ag_ui.core import RunErrorEvent
from pydantic_ai import CancellationToken, DeferredToolResults
from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import BaseAgent
from app.agents.tools import frontend_toolset, workspace_instructions
from app.agents.tools.workspace import workspace_tools
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, StorageUnavailableError, UnprocessableError
from app.enums import RunStatus
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.render.hub import RenderHub
from app.render.producer import RenderProducer
from app.schemas.run import RunCreate, RunResume
from app.schemas.run_item import ResourceItem
from app.services import chat_session as session_service
from app.services import file_service
from app.services import session_run as run_store
from app.services.artifacts import sync_run_artifacts
from app.services.model_factory import ModelFactory, ResolvedModel
from app.services.sandbox_pool import SandboxPool
from app.services.session_run import RUN_LEASE_SECONDS, ResumeDecisions
from app.services.storage import ObjectStorage, get_storage
from app.services.workspace import (
    LocalWorkspace,
    RunWorkspace,
    SandboxWorkspace,
    open_sandbox_workspace,
    sandbox_enabled,
)

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass
class RunRegistry:
    """运行任务与取消令牌的注册表；随 app.state 生命周期存在。"""

    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    cancellations: dict[str, tuple[UUID, CancellationToken]] = field(default_factory=dict)

    def schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def cancel_run(self, session_id: UUID, run_id: str) -> None:
        cancellation = self.cancellations.get(run_id)
        if cancellation is None or cancellation[0] != session_id:
            raise NotFoundError(f"Run {run_id} is not active")
        cancellation[1].cancel()

    async def cancel_all(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def launch_run(
    session: AsyncSession,
    session_id: UUID,
    payload: RunCreate | RunResume,
    *,
    owner_id: UUID,
    session_factory: SessionFactory,
    hub: RenderHub,
    registry: RunRegistry,
    sandbox_pool: SandboxPool | None = None,
) -> str:
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
            session, payload.attachments, owner=owner_id
        )
        # 引用的文件当场核对， ResourceItem 里带上官方记录的名字与大小
        resource_items = await file_service.resource_items_for(
            session, payload.resources, owner=owner_id
        )
        retry_run_id = payload.retry_run_id
        parent_run_id = payload.parent_run_id
        parent_was_given = payload.parent_was_given
        deferred_tool_results = None
        resume = None

    chat_session = await session_service.get_session_or_404(
        session, session_id, owner_id=owner_id
    )
    resolved_model_id = payload.model_id if payload.model_id is not None else chat_session.model_id
    if resolved_model_id is None:
        raise UnprocessableError(
            "Session has no model_id; set one on the session or in the request"
        )
    record = await session.get(LlmModel, resolved_model_id)
    if record is None or record.owner_id != owner_id:
        raise UnprocessableError(f"Model {resolved_model_id} not found")
    resolved = ModelFactory().create(record)
    toolset = frontend_toolset(payload.tools)

    # 生成 run id；session.active_run_id 由 start_run_turn 在同一事务里占用
    run_id = str(uuid4())
    producer = hub.create(session_id, run_id)
    try:
        await run_store.start_run_turn(
            session,
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
            cancellation_token=cancellation_token,
            registry=registry,
            toolset=toolset,
            sandbox_pool=sandbox_pool,
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
    cancellation_token: CancellationToken | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    registry: RunRegistry | None = None,
    toolset: AbstractToolset[Any] | None = None,
    sandbox_pool: SandboxPool | None = None,
) -> None:
    run_uuid = UUID(run_id)
    workspace: RunWorkspace | None = None
    error: str | None = None
    # 租约心跳：长工具调用期间不写 item，心跳保住租约，别的 resume 才抢不走
    heartbeat = asyncio.create_task(_renew_lease_loop(session_factory, session_id, run_id))
    try:
        async with session_factory() as db:
            workspace = await _build_workspace(db, session_id, run_id, sandbox_pool)
            # 本地模式没有注入资源时不开文件工具：纯聊天省事，TestModel 之类的
            # 顺序调用模型也不会被无关工具干扰；沙箱模式始终带着命令执行。
            run_obj = await run_store.get_run_or_404(db, session_id, run_uuid)
            offer_tools = isinstance(workspace, SandboxWorkspace) or any(
                isinstance(item, ResourceItem) for item in run_obj.content
            )
            wtools = (
                workspace_tools(
                    workspace,
                    session_factory,
                    owner_id=await _session_owner(session_factory, session_id),
                    settings=get_settings(),
                )
                if offer_tools
                else []
            )
            agent = BaseAgent(
                resolved.model,
                model_settings=resolved.settings,
                session=db,
                session_id=session_id,
                model_id=model_id,
                session_factory=session_factory,
                run_id=run_id,
                tools=wtools,
                prompt=workspace_instructions() if wtools else None,
            )
            # 用户消息已经在 start_run_turn 里写入，agent 只从 message_history 读
            async for event in agent.agui_events(
                None,
                run_id=run_id,
                deferred_tool_results=deferred_tool_results,
                cancellation_token=cancellation_token,
                toolsets=[toolset] if toolset is not None else None,
            ):
                await producer.publish(event)
    except asyncio.CancelledError:
        # 取消时未回填的 tool call 留在原地，用户可以再 resume 那条分支
        error = "run cancelled"
        raise
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        logger.exception("Run %s failed in session %s", run_id, session_id)
        with contextlib.suppress(Exception):
            async with session_factory() as db:
                await run_store.set_run_status(db, session_id, UUID(run_id), RunStatus.FAILED)
        with contextlib.suppress(Exception):
            await producer.publish(RunErrorEvent(message=error))
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        if registry is not None:
            registry.cancellations.pop(run_id, None)
        final_status = await _final_status(session_factory, session_id, run_uuid)
        await _shutdown_workspace(
            workspace, sandbox_pool, session_id=session_id, run_id=run_uuid,
            session_factory=session_factory, final_status=final_status,
        )
        await _release_run_lease(session_factory, session_id, run_id)
        await producer.close()


async def _build_workspace(
    db: AsyncSession, session_id: UUID, run_id: str, pool: SandboxPool | None
) -> RunWorkspace:
    """配好沙箱 → 云端工作区；否则本地临时目录。"""
    settings = get_settings()
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
        sandbox = await pool.acquire(session_id, run_id)
        return await open_sandbox_workspace(
            storage,
            session_id,
            run_id,
            sandbox,
            on_activity=lambda: pool.touch(session_id),
        )

    return LocalWorkspace(settings, storage, session_id, run_id)


async def _session_owner(
    session_factory: SessionFactory, session_id: UUID
) -> UUID | None:
    """产物归属跟会话主人走；查不到（会话被并发删了）就按匿名处理。"""
    try:
        async with session_factory() as db:
            value = await db.scalar(
                select(ChatSession.owner_id).where(ChatSession.id == session_id)
            )
            return value
    except Exception:
        return None


async def _final_status(
    session_factory: SessionFactory, session_id: UUID, run_id: UUID
) -> RunStatus | None:
    try:
        async with session_factory() as db:
            run = await run_store.get_run_or_404(db, session_id, run_id)
            return RunStatus(run.status)
    except Exception:
        return None


async def _shutdown_workspace(
    workspace: RunWorkspace | None,
    pool: SandboxPool | None,
    *,
    session_id: UUID,
    run_id: UUID,
    session_factory: SessionFactory,
    final_status: RunStatus | None,
) -> None:
    """收尾三件事：产物上传、工作区清退、沙箱按回收策略 pause/kill。"""
    if workspace is None:
        return
    try:
        if final_status in {RunStatus.COMPLETED, RunStatus.INTERRUPTED}:
            await sync_run_artifacts(
                workspace,
                session_factory=session_factory,
                session_id=session_id,
                run_id=run_id,
                settings=get_settings(),
                storage=get_storage(),
                owner=await _session_owner(session_factory, session_id),
            )
    except StorageUnavailableError:
        logger.info("No object storage configured; skipping artifact sync for %s", run_id)
    except Exception:
        logger.exception("Artifact sync failed for run %s", run_id)
    with contextlib.suppress(Exception):
        await workspace.cleanup()
    if pool is not None:
        try:
            if final_status == RunStatus.INTERRUPTED:
                await pool.release(session_id)
            else:
                await pool.discard(session_id)
        except Exception:
            logger.exception("Sandbox shutdown failed for run %s", run_id)


async def _renew_lease_loop(session_factory: SessionFactory, session_id: UUID, run_id: str) -> None:
    """按租约三分之一周期续租；续不上（借约已被抢）就保持沉默，正常退出即可。"""
    interval = RUN_LEASE_SECONDS / 3
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                await run_store.renew_run_lease(db, session_id, run_id)
        except Exception:
            logger.exception("Lease renewal failed for run %s in session %s", run_id, session_id)


async def _release_run_lease(
    session_factory: SessionFactory, session_id: UUID, run_id: str
) -> None:
    try:
        async with session_factory() as db:
            await run_store.finish_run(db, session_id, run_id)
    except Exception:
        # 清不掉会让前端一直以为 run 还在；租约到期后启动清扫会兜底
        logger.exception("Failed to release run lease %s in session %s", run_id, session_id)
