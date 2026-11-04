import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class SessionShare(TimestampMixin, Base):
    """会话的只读分享链接。

    库里不留明文口令：`token_hash` 用于公开读取的精确匹配，`token_encrypted`
    用同一个 SECRET_KEY 加密，只为了主人在「我的分享」里还能把链接复制出来。
    备份或库本身泄露时，拿到的是一堆解不开的哈希与密文，而不是可直接访问的链接。
    """

    __tablename__ = "session_shares"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 删会话时连带删掉它的分享链接
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    # 到期即失效；创建时必须给出，不允许永久链接
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    visit_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"SessionShare(id={self.id!r}, session_id={self.session_id!r})"
