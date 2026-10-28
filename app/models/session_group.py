from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class SessionGroup(TimestampMixin, Base):
    """用户自定义的会话分组；会话可以不属于任何分组。"""

    __tablename__ = "session_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 归属用户；NULL 视为迁移遗留的孤儿数据
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(60))
    # 手动排序留 10 的间隔，之后插入新组不用重排整表
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"SessionGroup(id={self.id!r}, name={self.name!r})"
