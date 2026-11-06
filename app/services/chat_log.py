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

from app.models.chat_request_log import ChatRequestLog
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services import billing

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
    # SQLite 读回来可能是 naive，按 UTC 解释才能和 finished 相减。
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    duration_ms = max(int((finished - created_at).total_seconds() * 1000), 0)
    log = await db.scalar(
        select(ChatRequestLog)
        .where(ChatRequestLog.run_id == run_id)
        .order_by(ChatRequestLog.created_at.desc())
        .limit(1)
    )
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
            error=error[:500] if error else None,
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
        log.error = error[:500] if error else None
        log.duration_ms = duration_ms
        log.finished_at = finished
    await db.commit()
    return log
