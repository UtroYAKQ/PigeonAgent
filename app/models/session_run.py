import uuid

from pydantic import TypeAdapter
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PydanticJson
from app.enums import RunKind, RunStatus
from app.models.mixins import TimestampMixin
from app.schemas.run_item import RunItem, TokenUsage

RunItemList = TypeAdapter(list[RunItem])


class SessionRun(TimestampMixin, Base):
    """一次 run；多个 run 用 parent_run_id 组成树。

    用户所在分支就是从 active_leaf_run_id 往根走的那条链，所以当前分支永远可以
    当线性日志读；同一父节点的多个子 run 就是同一处的多个版本。
    """

    __tablename__ = "session_runs"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_session_runs_session_id_seq"),
        CheckConstraint("parent_run_id <> id", name="ck_session_runs_no_self_parent"),
        Index("ix_session_runs_parent", "session_id", "parent_run_id"),
        Index("ix_session_runs_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    # SET NULL：个别 run 被整掉时，活下来的子 run 自己成为新的根，
    # 跟着级联会把整条分支抹掉。
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("session_runs.id", ondelete="SET NULL"), default=None
    )
    # 全局创建序号；路径顺序就是 seq 升序
    seq: Mapped[int] = mapped_column(BigInteger)
    # running | completed | interrupted | failed | cancelled
    status: Mapped[str] = mapped_column(
        String(16), default=RunStatus.RUNNING.value, server_default=text("'running'")
    )
    # turn | resume
    kind: Mapped[str] = mapped_column(
        String(16), default=RunKind.TURN.value, server_default=text("'turn'")
    )
    # 类型化事件列表
    content: Mapped[list[RunItem]] = mapped_column(PydanticJson(RunItemList), default=list)
    # 本 run 使用的模型
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="SET NULL"), default=None
    )
    # 分支预览文本，避免树接口反序列化整份 content
    preview: Mapped[str] = mapped_column(String(2000), default="", server_default=text("''"))
    # 本 run 自己产生的 token 用量
    usage: Mapped[TokenUsage] = mapped_column(
        PydanticJson(TokenUsage), default=TokenUsage, server_default=text("'{}'")
    )

    def __repr__(self) -> str:
        return f"SessionRun(id={self.id!r}, seq={self.seq!r}, status={self.status!r})"
