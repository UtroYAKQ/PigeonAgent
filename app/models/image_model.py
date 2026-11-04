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


class ImageModel(TimestampMixin, Base):
    """一个可用的图片生成模型。与 LlmModel 一样是全局资源，只有管理员能改。

    对话模型走 Pydantic AI 的 Model 接口，图片模型是另一套协议，
    所以单独建表、单独工厂，不塞进 llm_models。
    """

    __tablename__ = "image_models"
    __table_args__ = (
        CheckConstraint("max_images > 0 AND max_images <= 8", name="ck_image_models_max_images"),
        Index(
            "uq_image_models_single_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 展示名（唯一）
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 供应商 key，决定 base_url 与常用尺寸
    provider: Mapped[str] = mapped_column(String(32))
    # LiteLLM 的调用协议（provider route）：openai / azure / bedrock / ...
    protocol: Mapped[str] = mapped_column(
        String(32), default="openai", server_default=text("'openai'")
    )
    # 展示用厂商图标 key
    icon: Mapped[str | None] = mapped_column(String(64))
    # 供应商侧的模型名，例如 gpt-image-1、seedream-4.0
    model_name: Mapped[str] = mapped_column(String(128))
    # 自定义网关地址；为空时走供应商默认
    base_url: Mapped[str | None] = mapped_column(String(512))
    # 加密后的 API Key
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    # 允许模型选择的尺寸档，例如 ["1024x1024", "1536x1024"]
    sizes: Mapped[list[str]] = mapped_column(JsonDict, default=list, server_default=text("'[]'"))
    # 未指定尺寸时用哪一档；必须是 sizes 里的值
    default_size: Mapped[str] = mapped_column(String(32), default="1024x1024")
    # 单次最多生成几张
    max_images: Mapped[int] = mapped_column(Integer, default=4, server_default=text("4"))
    # 画质档位，透传给上游；为空表示不传
    quality: Mapped[str | None] = mapped_column(String(32))
    # 积分单价：每生成一张图多少积分；为空时回落全局默认
    credit_per_image: Mapped[float | None] = mapped_column(Float)
    # 是否可被选择
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 是否为默认图片模型（全局唯一）
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    def __repr__(self) -> str:
        return f"ImageModel(id={self.id!r}, name={self.name!r}, provider={self.provider!r})"
