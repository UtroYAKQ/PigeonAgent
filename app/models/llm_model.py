from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class LlmModel(TimestampMixin, Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        CheckConstraint(
            "context_window IS NULL OR context_window > 0",
            name="ck_llm_models_context_window_positive",
        ),
        CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens > 0",
            name="ck_llm_models_max_output_tokens_positive",
        ),
        Index(
            "uq_llm_models_owner_single_default",
            "owner_id",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
    )

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True)
    # 归属用户；每个用户各自管自己的模型与默认项
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    # 展示名（唯一）
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 供应商标识（openai 等）
    provider: Mapped[str] = mapped_column(String(32))
    # 供应商侧的模型名
    model_name: Mapped[str] = mapped_column(String(128))
    # 自定义网关地址；为空走供应商默认
    base_url: Mapped[str | None] = mapped_column(String(512))
    # 加密后的 API Key
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    # 上下文窗口 token 数
    context_window: Mapped[int | None] = mapped_column(Integer)
    # 单次最大输出 token 数
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    # 是否支持工具调用
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 是否可被选择
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 是否为默认模型（全局最多一个）
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    def __repr__(self) -> str:
        return f"LlmModel(id={self.id!r}, name={self.name!r}, provider={self.provider!r})"
