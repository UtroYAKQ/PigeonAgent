import asyncio
import time

from pydantic_ai import Agent, ModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import UnprocessableError, describe_error
from app.infra.providers.llm import ModelFactory
from app.models.ai.llm import LlmModel
from app.schemas.model.llm import (
    LlmModelCreate,
    LlmModelProbeResult,
    LlmModelUpdate,
)
from app.services.model import catalog as _model_catalog

# 模型是全局资源：所有成员共享同一份列表，写入权限由端点层的管理员依赖把关。
# 与 image_model 同构的目录化 CRUD 原语在 _model_catalog，本模块只留 LLM 表特有的差异。

LLM_CATALOG = _model_catalog.ModelCatalog(cls=LlmModel, label="Model")


async def list_models(db: AsyncSession, *, limit: int, offset: int) -> tuple[list[LlmModel], int]:
    return await _model_catalog.list_models(db, LLM_CATALOG, limit=limit, offset=offset)


async def get_model_or_404(db: AsyncSession, model_id: int) -> LlmModel:
    return await _model_catalog.get_model_or_404(db, LLM_CATALOG, model_id)


async def create_model(
    db: AsyncSession, payload: LlmModelCreate, *, secret_key: str | None
) -> LlmModel:
    if payload.compaction_threshold is not None and payload.context_window is None:
        raise UnprocessableError("设置压缩阈值前必须先设置 context_window")
    values = payload.model_dump(exclude={"api_key"})
    values["provider"] = payload.provider.value
    values["thinking_levels"] = [level.value for level in payload.thinking_levels]
    values["api_key_encrypted"] = _model_catalog.encrypt_api_key(payload.api_key, secret_key)
    if payload.is_default:
        await _model_catalog.clear_defaults(db, LLM_CATALOG)

    model = LlmModel(**values)
    db.add(model)
    await _model_catalog.commit_or_conflict(db, LLM_CATALOG, model.name)
    await db.refresh(model)
    return model


async def update_model(
    db: AsyncSession,
    model_id: int,
    payload: LlmModelUpdate,
    *,
    secret_key: str | None,
) -> LlmModel:
    model = await get_model_or_404(db, model_id)
    data = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    if "context_window" in data or "compaction_threshold" in data:
        next_window = data.get("context_window", model.context_window)
        next_threshold = data.get("compaction_threshold", model.compaction_threshold)
        if next_threshold is not None and next_window is None:
            raise UnprocessableError("设置压缩阈值前必须先设置 context_window")
    if payload.provider is not None:
        data["provider"] = payload.provider.value
    if payload.thinking_levels is not None:
        data["thinking_levels"] = [level.value for level in payload.thinking_levels]
    if "api_key" in payload.model_fields_set:
        data["api_key_encrypted"] = _model_catalog.encrypt_api_key(payload.api_key, secret_key)
    if data.get("is_default") is True:
        await _model_catalog.clear_defaults(db, LLM_CATALOG)

    for field_name, value in data.items():
        setattr(model, field_name, value)
    await _model_catalog.commit_or_conflict(db, LLM_CATALOG, model.name)
    await db.refresh(model)
    return model


async def delete_model(db: AsyncSession, model_id: int) -> None:
    model = await get_model_or_404(db, model_id)
    await db.delete(model)
    await db.commit()


PROBE_TIMEOUT_SECONDS = 30.0
PROBE_MAX_TOKENS = 256
# 让模型做一次真实的小生成，而不是只回声 OK；输出会直接展示给管理员
PROBE_PROMPT = "请用一句不超过 30 字的中文介绍你自己。"


async def probe_model(model: LlmModel, *, settings: Settings) -> LlmModelProbeResult:
    """发一条短请求验证模型配置；停用中的模型也允许探测。"""
    started = time.perf_counter()
    latency_ms = 0
    try:
        resolved = ModelFactory(settings).create(model, require_active=False)
        probe_settings = ModelSettings(**resolved.settings)
        probe_settings["max_tokens"] = PROBE_MAX_TOKENS
        agent = Agent(resolved.model, model_settings=probe_settings)
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            result = await agent.run(PROBE_PROMPT)
        latency_ms = int((time.perf_counter() - started) * 1000)
        output = str(result.output).strip()[:200]
        if not output:
            return LlmModelProbeResult(
                ok=False,
                latency_ms=latency_ms,
                error="模型返回了空内容，请检查模型配置或最大输出设置",
            )
        return LlmModelProbeResult(ok=True, latency_ms=latency_ms, output=output)
    except Exception as exc:
        return LlmModelProbeResult(
            ok=False,
            latency_ms=latency_ms or int((time.perf_counter() - started) * 1000),
            error=describe_error(exc),
        )
