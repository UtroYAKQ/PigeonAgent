"""run 期间的积分守卫：按水位差实时结算，余额见底就停掉本轮。

守卫只做两件事——算账、决定该不该停。一轮为什么结束、怎么让用户看见，归
`AgentTurn`：这里只抛 `CreditsExhausted`，由 `summarize_error` 归类成
`credits_exhausted` 落进 run 历史并下发错误事件。观察者抛出的其它异常会被
`SessionStore` 吞掉（计费故障不该打断对话），只有这个停止信号被放行。

兜底的最后一批结算在 `run.py` 的收尾里，不靠这里。
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.agents.runtime.store import UsageObserver
from app.core.config import Settings
from app.core.exceptions import CreditsExhausted
from app.db.session import SessionFactory
from app.domain.run_items import TokenUsage
from app.services.billing import service as billing

logger = logging.getLogger(__name__)


def make_usage_guard(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    session_id: UUID,
    run_id: UUID,
    owner_id: UUID | None,
) -> UsageObserver:
    """一轮 run 装配一个：run_id 和归属用户都是 run 级的。"""

    async def guard(_: TokenUsage) -> None:
        # 不读用量本身：结算按库里已落的水位差算，观察者只是「该查一次了」的信号
        if not settings.billing_enabled:
            return
        async with session_factory() as db:
            await billing.settle_run(db, settings, session_id=session_id, run_id=run_id)
            # 没有归属用户就无从判断余额，让它继续跑
            if owner_id is None:
                return
            balance = await billing.balance_of(db, owner_id)
        if balance > 0:
            return
        logger.warning("Credits exhausted mid-run %s (balance %s); stopping", run_id, balance)
        raise CreditsExhausted(f"Run {run_id} is out of credits (balance {balance})")

    return guard
