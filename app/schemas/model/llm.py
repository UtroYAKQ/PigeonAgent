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

from app.enums import LlmProvider, ThinkingLevel

ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
UpstreamModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]


class LlmModelBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName
    provider: LlmProvider
    icon: str | None = Field(default=None, max_length=64)
    model_name: UpstreamModelName
    base_url: str | None = Field(default=None, max_length=512)
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    compaction_threshold: float | None = Field(default=None, ge=0.1, le=1.0)
    # 积分单价：每 100 万 token 扣多少积分；留空用全局默认
    credit_input_per_1m: float | None = Field(default=None, ge=0)
    credit_output_per_1m: float | None = Field(default=None, ge=0)
    credit_cache_read_per_1m: float | None = Field(default=None, ge=0)
    thinking_levels: list[ThinkingLevel] = Field(default_factory=list, max_length=6)
    supports_tools: bool = True
    is_active: bool = True
    is_default: bool = False

    @field_validator("thinking_levels")
    @classmethod
    def _thinking_levels_are_unique(cls, value: list[ThinkingLevel]) -> list[ThinkingLevel]:
        return list(dict.fromkeys(value))


class LlmModelCreate(LlmModelBase):
    api_key: SecretStr | None = None


class LlmModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName | None = None
    provider: LlmProvider | None = None
    icon: str | None = Field(default=None, max_length=64)
    model_name: UpstreamModelName | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    compaction_threshold: float | None = Field(default=None, ge=0.1, le=1.0)
    credit_input_per_1m: float | None = Field(default=None, ge=0)
    credit_output_per_1m: float | None = Field(default=None, ge=0)
    credit_cache_read_per_1m: float | None = Field(default=None, ge=0)
    thinking_levels: list[ThinkingLevel] | None = Field(default=None, max_length=6)
    supports_tools: bool | None = None
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("thinking_levels")
    @classmethod
    def _thinking_levels_are_unique(
        cls, value: list[ThinkingLevel] | None
    ) -> list[ThinkingLevel] | None:
        return list(dict.fromkeys(value)) if value is not None else None

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_fields(self) -> Self:
        non_nullable = {
            "name",
            "provider",
            "model_name",
            "thinking_levels",
            "supports_tools",
            "is_active",
            "is_default",
        }
        for field_name in non_nullable & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class LlmModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: LlmProvider
    icon: str | None
    model_name: str
    base_url: str | None
    context_window: int | None
    max_output_tokens: int | None
    compaction_threshold: float | None
    credit_input_per_1m: float | None
    credit_output_per_1m: float | None
    credit_cache_read_per_1m: float | None
    thinking_levels: list[ThinkingLevel]
    supports_tools: bool
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class LlmModelList(BaseModel):
    items: list[LlmModelRead]
    total: int
