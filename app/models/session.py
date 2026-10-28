import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PydanticJson
from app.models.mixins import TimestampMixin
from app.schemas.run_item import TokenUsage


class ChatSession(TimestampMixin, Base):
    """会话头 + 当前运行状态。"""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 归属用户；所有列表/读取都按它过滤，NULL 视为迁移遗留的孤儿数据
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="SET NULL"), index=True
    )
    # 所属分组；删组时回到未分组，绝不连带删会话
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_groups.id", ondelete="SET NULL"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default=text("'active'")
    )
    # 数据格式版本；run 树 + 类型化 item 为 5
    format_version: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    # run 序号分配器
    run_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    # 全量 token 累计，写 run 时同事务增量更新
    usage: Mapped[TokenUsage] = mapped_column(
        PydanticJson(TokenUsage),
        default=TokenUsage,
        server_default=text("'{}'"),
    )
    # 当前执行中的 run；等待 resume 时为空
    active_run_id: Mapped[str | None] = mapped_column(String(36))
    # run 租约到期时间；worker 崩了也不会永久卡住会话
    active_run_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 当前分支的叶子 run；上下文、分页和重新生成都从它往根走。
    # 故意不建外键：sessions ↔ session_runs 互相引用会让 SQLite 无法建/删表。
    active_leaf_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    # 最近一次写入 run 的时间，用于会话排序
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"ChatSession(id={self.id!r}, title={self.title!r}, status={self.status!r})"
