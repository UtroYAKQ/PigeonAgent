from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JsonDict


class OperationLog(Base):
    """所有 HTTP 操作与管理员语义操作的统一日志。

    普通请求的 body 大小由采集层截断；管理员操作沿用 action/target/detail。
    """

    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("ix_operation_logs_created_at", "created_at"),
        Index("ix_operation_logs_actor_created", "actor_id", "created_at"),
        Index("ix_operation_logs_route_created", "route", "created_at"),
        Index("ix_operation_logs_status_created", "status_code", "created_at"),
        Index("ix_operation_logs_request_id", "request_id"),
        Index("ix_operation_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(
        String(16), default="request", server_default=text("'request'")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_email: Mapped[str | None] = mapped_column(String(254))
    method: Mapped[str | None] = mapped_column(String(10))
    path: Mapped[str | None] = mapped_column(String(1024))
    route: Mapped[str | None] = mapped_column(String(255))
    query: Mapped[Any | None] = mapped_column(JsonDict)
    request_body: Mapped[Any | None] = mapped_column(JsonDict)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[Any | None] = mapped_column(JsonDict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    request_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    response_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    request_truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    response_truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    action: Mapped[str | None] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JsonDict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"OperationLog(id={self.id!r}, method={self.method!r}, path={self.path!r})"
