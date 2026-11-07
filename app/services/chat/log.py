"""对话请求日志：run 收尾时留一条，供后台按用户/时间回看。

同一 run 中断后续写会多次收尾，日志按 run_id 更新同一条，
不会把一轮对话拆成多条请求记录。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.time import ensure_utc
from app.models.ai.llm import LlmModel
from app.models.chat.log import ChatRequestLog
from app.models.chat.run import SessionRun
from app.models.chat.session import ChatSession
from app.services.billing import service as billing

logger = logging.getLogger(__name__)


async def finish_run_log(
    db: AsyncSession,
    *,
    session_id: UUID,
    run_id: UUID,
    status: str | None,
    error: str | None,
    started_at: datetime,
) -> ChatRequestLog | None:
    """run 收尾留痕。

    credits_charged 从流水里汇总而不是拿收尾结算的返回值：实时结算
    （余额观察者）在轮内已经扣过钱，收尾的水位差通常是 0，只记那一笔
    会让日志显示"没扣分"，账和流水对不上。
    """
    run = await db.get(SessionRun, run_id)
    if run is None:
        return None
    owner_id = await db.scalar(select(ChatSession.owner_id).where(ChatSession.id == session_id))
    model = await db.get(LlmModel, run.model_id) if run.model_id is not None else None
    finished = datetime.now(UTC)
    totals = await billing.run_charge_totals(db, run_id)
    # 以 run 起点算整轮时长；resume 那次 started_at 只是续写段的起点。
    duration_ms = max(int((finished - ensure_utc(run.created_at)).total_seconds() * 1000), 0)
    log = await db.scalar(select(ChatRequestLog).where(ChatRequestLog.run_id == run_id))
    log_error = error[:500] if error else None
    if log is None:
        log = ChatRequestLog(
            user_id=owner_id,
            session_id=session_id,
            run_id=run_id,
            status=status or "unknown",
            model_id=run.model_id,
            model_name=model.name if model is not None else None,
            usage=run.usage,
            credits_charged=totals.credits,
            images_generated=totals.images,
            error=log_error,
            duration_ms=duration_ms,
            finished_at=finished,
        )
        db.add(log)
    else:
        # 中断后续写：同一轮只保留一条日志，更新到最后一次收尾
        log.user_id = owner_id
        log.session_id = session_id
        log.status = status or "unknown"
        log.model_id = run.model_id
        log.model_name = model.name if model is not None else None
        log.usage = run.usage
        log.credits_charged = totals.credits
        log.images_generated = totals.images
        log.error = log_error
        log.duration_ms = duration_ms
        log.finished_at = finished
    await db.commit()
    return log
