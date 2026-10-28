from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, model_validator

from app.enums import LlmProvider

ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
UpstreamModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]


class LlmModelBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName
    provider: LlmProvider
    model_name: UpstreamModelName
    base_url: str | None = Field(default=None, max_length=512)
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supports_tools: bool = True
    is_active: bool = True
    is_default: bool = False


class LlmModelCreate(LlmModelBase):
    api_key: SecretStr | None = None


class LlmModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ModelName | None = None
    provider: LlmProvider | None = None
    model_name: UpstreamModelName | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supports_tools: bool | None = None
    is_active: bool | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def reject_null_for_non_nullable_fields(self) -> Self:
        non_nullable = {
            "name",
            "provider",
            "model_name",
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
    model_name: str
    base_url: str | None
    context_window: int | None
    max_output_tokens: int | None
    supports_tools: bool
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class LlmModelList(BaseModel):
    items: list[LlmModelRead]
    total: int
