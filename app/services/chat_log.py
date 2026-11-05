"""对话请求日志：run 收尾时留一条，供后台按用户/时间回看。

只有 run 收尾一个写入点，和计费结算并列——它俩看的都是同一份 run.usage。
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
    log = ChatRequestLog(
        user_id=owner_id,
        session_id=session_id,
        run_id=run_id,
        kind=run.kind,
        # run 已经结束才会有这条日志；状态读不出来就写 unknown，不要伪造"还在跑"
        status=status or "unknown",
        model_id=run.model_id,
        model_name=model.name if model is not None else None,
        usage=run.usage,
        credits_charged=totals.credits,
        images_generated=totals.images,
        error=error[:500] if error else None,
        duration_ms=max(int((finished - started_at).total_seconds() * 1000), 0),
        finished_at=finished,
    )
    db.add(log)
    await db.commit()
    return log
