"""开轮入口：校验请求与模型能力，占用 run 后交给执行器。"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic_ai import CancellationToken, DeferredToolResults
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import frontend_toolset
from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, UnprocessableError
from app.db.session import SessionFactory
from app.domain.run_items import RunItem
from app.infra.model_factory import ModelFactory
from app.models.llm_model import LlmModel
from app.render.hub import RenderHub
from app.sandbox.pool import SandboxPool
from app.schemas.run import RunCreate, RunResume
from app.services import billing, file_service
from app.services import chat_session as session_service
from app.services import image_model as image_model_service
from app.services.run.execute import execute_run
from app.services.run.options import _supported_thinking_level
from app.services.run.pending import pending_batches
from app.services.run.registry import RunRegistry
from app.services.run.store import start_run_turn
from app.services.run.types import PendingBatch, ResumeDecisions


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
    resume_batch: PendingBatch | None = None
    if isinstance(payload, RunResume):
        user_input = None
        attachments = []
        retry_run_id = parent_run_id = None
        has_explicit_parent = False
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
        has_explicit_parent = payload.has_explicit_parent
        deferred_tool_results = None
        resume = None

    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=owner_id)
    resolved_model_id = payload.model_id if payload.model_id is not None else chat_session.model_id
    if resolved_model_id is None:
        raise UnprocessableError("会话没有 model_id；请在会话或请求里指定模型")
    record = await db.get(LlmModel, resolved_model_id)
    if record is None:
        raise UnprocessableError(f"模型 {resolved_model_id} 不存在")
    resolved = ModelFactory().create(record)
    thinking_level = _supported_thinking_level(record, chat_session.thinking_level)
    toolset = frontend_toolset(payload.tools)
    # 平台总闸优先：关掉之后，客户端即使传了 true 也不下发工具
    enable_web_search = payload.enable_web_search and runtime.feature_web_search_enabled
    enable_image_generation = (
        payload.enable_image_generation and runtime.feature_image_generation_enabled
    )
    image_model_id = payload.image_model_id if enable_image_generation else None
    if not resolved.supports_tools:
        if isinstance(payload, RunResume):
            raise UnprocessableError(
                "当前模型不支持工具调用，无法恢复待审批/外部调用；请先切换到支持工具的模型"
            )
        if enable_web_search or resource_items:
            raise UnprocessableError(
                f"模型「{record.name}」未开启工具调用支持，无法使用联网搜索或文件工作区"
            )
        # 生图同样依赖工具调用，连图片模型一起忽略；
        # 能力被关掉就不再校验它的配置，非工具模型不该被图片模型拦成 422
        toolset = None
        enable_image_generation = False
        image_model_id = None
    # 明确选了一个不可用的模型时当场拒掉；后台再发现就没法给请求返回 422 了
    if (
        image_model_id is not None
        and await image_model_service.get_active_model(db, image_model_id) is None
    ):
        raise UnprocessableError("所选图片模型不可用，请重新选择")
    if enable_web_search and not runtime.deepseek_api_key:
        raise UnprocessableError("联网搜索未配置：请在配置项里填写 DeepSeek API Key")
    # 积分不足就在开跑前拦下：跑完再告知"你欠费了"是最糟的体验
    await billing.require_credits(db, runtime, owner_id)

    if isinstance(payload, RunResume):
        resume_batch = next(
            (
                item
                for item in await pending_batches(db, session_id)
                if item.interrupt_id == payload.interrupt_id
            ),
            None,
        )
        if resume_batch is None:
            raise ConflictError(f"Interrupt batch {payload.interrupt_id} is not pending")
        # 同一轮续写：沿用声明批次的那条 run，事件流也复用同一个 id
        run_id = str(resume_batch.run_id)
    else:
        # 生成 run id；session.active_run_id 由 start_run_turn 在同一事务里占用
        run_id = str(uuid4())
    producer = await hub.create(session_id, run_id)
    try:
        await start_run_turn(
            db,
            session_id,
            run_id=run_id,
            user_input=user_input,
            attachments=attachments,
            resource_items=resource_items,
            retry_run_id=retry_run_id,
            parent_run_id=parent_run_id,
            has_explicit_parent=has_explicit_parent,
            resume=resume,
            resume_batch=resume_batch,
            model_id=resolved_model_id,
        )
    except Exception:
        await producer.close()
        raise

    cancellation_token = CancellationToken()
    await registry.register(run_id, session_id, cancellation_token)
    registry.schedule(
        execute_run(
            producer=producer,
            session_factory=session_factory,
            session_id=session_id,
            run_id=run_id,
            owner_id=owner_id,
            deferred_tool_results=deferred_tool_results,
            resolved=resolved,
            model_id=resolved_model_id,
            thinking_level=thinking_level,
            cancellation_token=cancellation_token,
            registry=registry,
            toolset=toolset,
            enable_web_search=enable_web_search,
            enable_image_generation=enable_image_generation,
            image_model_id=image_model_id,
            sandbox_pool=sandbox_pool,
            settings=runtime,
        )
    )
    return run_id
