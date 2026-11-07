from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("group name cannot be blank")
        return cleaned


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int
    session_count: int = 0
    created_at: datetime
    updated_at: datetime


class GroupList(BaseModel):
    items: list[GroupRead]
    total: int
