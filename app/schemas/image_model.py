from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.enums import ImageProtocol, ImageProvider

ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
UpstreamModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
# 尺寸档只接受 WxH 形式，避免把任意字符串透传给上游
SizeSpec = Annotated[str, StringConstraints(pattern=r"^\d{2,5}x\d{2,5}$")]

DEFAULT_SIZES = ("1024x1024", "1536x1024", "1024x1536")


def _deduped_sizes(value: list[SizeSpec]) -> list[SizeSpec]:
    """尺寸档去重保序；一个都不剩就拒——没有尺寸就没法出图。"""
    cleaned = list(dict.fromkeys(value))
    if not cleaned:
        raise ValueError("at least one size is required")
    return cleaned


class ImageModelBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName
    provider: ImageProvider = ImageProvider.OPENAI
    # 调用协议（LiteLLM 的 provider route）；留空时回落到供应商预设
    protocol: ImageProtocol | None = None
    icon: str | None = Field(default=None, max_length=64)
    model_name: UpstreamModelName
    base_url: str | None = Field(default=None, max_length=512)
    sizes: list[SizeSpec] = Field(default_factory=lambda: list(DEFAULT_SIZES), max_length=8)
    default_size: SizeSpec = "1024x1024"
    max_images: int = Field(default=4, ge=1, le=8)
    quality: str | None = Field(default=None, max_length=32)
    # 积分单价：每生成一张图扣多少积分；留空用全局默认
    credit_per_image: float | None = Field(default=None, ge=0)
    is_active: bool = True
    is_default: bool = False

    @field_validator("sizes")
    @classmethod
    def _sizes_are_unique(cls, value: list[SizeSpec]) -> list[SizeSpec]:
        return _deduped_sizes(value)

    @model_validator(mode="after")
    def _default_size_is_supported(self) -> Self:
        if self.sizes and self.default_size not in self.sizes:
            raise ValueError("default_size must be one of sizes")
        return self


class ImageModelCreate(ImageModelBase):
    api_key: SecretStr | None = None


class ImageModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName | None = None
    provider: ImageProvider | None = None
    protocol: ImageProtocol | None = None
    icon: str | None = Field(default=None, max_length=64)
    model_name: UpstreamModelName | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr | None = None
    sizes: list[SizeSpec] | None = Field(default=None, max_length=8)
    default_size: SizeSpec | None = None
    max_images: int | None = Field(default=None, ge=1, le=8)
    quality: str | None = Field(default=None, max_length=32)
    credit_per_image: float | None = Field(default=None, ge=0)
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("sizes")
    @classmethod
    def _sizes_are_unique(cls, value: list[SizeSpec] | None) -> list[SizeSpec] | None:
        # PATCH 不带这个字段就是不动尺寸
        return None if value is None else _deduped_sizes(value)

    @model_validator(mode="after")
    def _validate_partial(self) -> Self:
        non_nullable = {"name", "provider", "model_name", "sizes", "default_size", "max_images"}
        for field_name in non_nullable & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if (
            self.sizes is not None
            and self.default_size is not None
            and self.default_size not in self.sizes
        ):
            raise ValueError("default_size must be one of sizes")
        return self


class ImageModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: ImageProvider
    protocol: ImageProtocol
    icon: str | None
    model_name: str
    base_url: str | None
    sizes: list[str]
    default_size: str
    max_images: int
    quality: str | None
    credit_per_image: float | None
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ImageModelList(BaseModel):
    items: list[ImageModelRead]
    total: int


class ImageProviderRead(BaseModel):
    """供应商预设：前端选完就能带出地址、尺寸和模型名示例。"""

    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    protocol: str
    base_url: str | None
    # 相对 base_url 的路径，前端据此拼出最终地址做预览
    path: str
    model_hint: str
    sizes: list[str]
    note: str | None = None
