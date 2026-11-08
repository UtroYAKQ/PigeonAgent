"""管理员配置的 MCP 服务器。

首期只支持远程 Streamable HTTP；token 加密存储，前端永远拿不到明文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class McpServer(TimestampMixin, Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 展示名，管理员和用户都看这个
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 工具名前缀；同一平台内唯一，避免多个服务器撞名
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # MCP Streamable HTTP 端点
    url: Mapped[str] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(String(500))
    # 加密后的 Bearer token；为空表示无需认证
    auth_encrypted: Mapped[str | None] = mapped_column(Text)
    # 管理员停用后，用户不能再选，已在会话里的选择也会在开跑时被过滤
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 工具调用前是否必须由用户确认
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 是否把工具 schema 交给 pydantic-ai 的按需发现机制
    defer_loading: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, server_default=text("120"))
    # 最近一次“测试连接”看到的工具数量
    tool_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def has_auth(self) -> bool:
        return bool(self.auth_encrypted)

    def __repr__(self) -> str:
        return f"McpServer(id={self.id!r}, name={self.name!r}, slug={self.slug!r})"
