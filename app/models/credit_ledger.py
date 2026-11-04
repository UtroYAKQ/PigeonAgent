"""积分流水：每一笔增减都留一条，余额只是它的冗余投影。

只增不改不删——算错账靠反向条目纠正（reason=adjust），不回溯改写历史。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.types import JsonDict
from app.models.mixins import TimestampMixin

# 对账口径：chat 是一次 run 的文本结算，image 是一次成功出图
CHAT = "chat"
IMAGE = "image"
ADJUST = "adjust"


class CreditLedger(TimestampMixin, Base):
    __tablename__ = "credit_ledgers"
    __table_args__ = (
        # 结算幂等靠它：一个 run 的 chat 条目累积起来就是已结算水位
        Index("ix_credit_ledgers_run_reason", "run_id", "reason"),
        Index("ix_credit_ledgers_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 归属用户；用户被删时流水保留（对账需要），故不级联
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 负数扣费、正数充值；单位是积分，支持小数（按 token 线性折算）
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    # 结账后的余额快照，便于直接展示，不必重放历史
    balance_after: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    # 关联的 run；adjust 之类的人工条目为空
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # 计价用的模型：llm / image + 模型表主键
    model_kind: Mapped[str | None] = mapped_column(String(8))
    model_id: Mapped[int | None] = mapped_column(Integer)
    # 本次结算覆盖的用量（TokenUsage 的 dict）或出图张数，用于对账
    usage: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    note: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return (
            f"CreditLedger(user_id={self.user_id!r}, delta={self.delta!r}, reason={self.reason!r})"
        )
