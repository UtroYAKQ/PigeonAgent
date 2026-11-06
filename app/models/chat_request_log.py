"""一次对话请求的留痕：谁、用哪个模型、花了多少 token 和积分。

和 credit_ledgers 的分工：那边是账（只增不改，用于对账），这边是请求日志
（按时间查"某次对话到底跑了什么"）。用量和扣分在这里做一次快照，看日志
就不用再回头 join 账本。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.types import PydanticJson
from app.domain.run_items import TokenUsage


class ChatRequestLog(Base):
    __tablename__ = "chat_request_logs"
    __table_args__ = (
        Index("ix_chat_request_logs_user_created", "user_id", "created_at"),
        Index("ix_chat_request_logs_session_created", "session_id", "created_at"),
        Index("ix_chat_request_logs_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 本地/无主会话为空
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # completed | interrupted | failed | cancelled | running
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default=text("'running'")
    )
    model_id: Mapped[int | None] = mapped_column(ForeignKey("llm_models.id", ondelete="SET NULL"))
    # 模型名冗余一份：模型被删后日志仍然可读
    model_name: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[TokenUsage] = mapped_column(
        PydanticJson(TokenUsage), default=TokenUsage, server_default=text("'{}'")
    )
    # 本次请求扣掉的积分（文本+图片），0 表示未计费或开关关闭
    credits_charged: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    images_generated: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"ChatRequestLog(run_id={self.run_id!r}, status={self.status!r})"
