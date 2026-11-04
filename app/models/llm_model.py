from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    Index,
    Integer,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db.types import JsonDict
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
        CheckConstraint(
            "compaction_threshold IS NULL OR "
            "(compaction_threshold >= 0.1 AND compaction_threshold <= 1)",
            name="ck_llm_models_compaction_threshold_range",
        ),
        Index(
            "uq_llm_models_single_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
    )

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True)
    # 展示名（唯一）
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 供应商标识（openai 等）
    provider: Mapped[str] = mapped_column(String(32))
    # 展示用厂商图标 key（对应前端图标库，如 deepseek、qwen）
    icon: Mapped[str | None] = mapped_column(String(64))
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
    # 上下文压缩触发比例（0.1~1.0）；为空时使用全局默认
    compaction_threshold: Mapped[float | None] = mapped_column(Float)
    # 该模型允许选择的思考挡位；为空表示不展示挡位
    thinking_levels: Mapped[list[str]] = mapped_column(
        JsonDict, default=list, server_default=text("'[]'")
    )
    # 是否支持工具调用
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 是否可被选择
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 积分单价：每 100 万 token 多少积分；为空时回落全局默认
    credit_input_per_1m: Mapped[float | None] = mapped_column(Float)
    credit_output_per_1m: Mapped[float | None] = mapped_column(Float)
    # 缓存命中单价；留空按输入单价
    credit_cache_read_per_1m: Mapped[float | None] = mapped_column(Float)
    # 是否为默认模型（全局唯一；模型对所有成员共享，仅管理员可配置）
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    def __repr__(self) -> str:
        return f"LlmModel(id={self.id!r}, name={self.name!r}, provider={self.provider!r})"
