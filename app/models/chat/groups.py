from __future__ import annotations

import uuid

from sqlalchemy import Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class SessionGroup(TimestampMixin, Base):
    """用户自定义的会话分组；会话可以不属于任何分组。"""

    __tablename__ = "session_groups"
    __table_args__ = (
        # 同一用户下分组名唯一；owner_id 为 NULL 的遗留行不受约束
        Index("uq_session_groups_owner_id_name", "owner_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 归属用户；NULL 视为迁移遗留的孤儿数据
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(60))
    # 手动排序留 10 的间隔，之后插入新组不用重排整表
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"SessionGroup(id={self.id!r}, name={self.name!r})"
