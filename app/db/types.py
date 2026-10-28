"""JSON 列的类型装饰器：DB 存 JSON，Python 侧是 Pydantic 模型或 TypeAdapter。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

# Postgres 用 JSONB（可索引、读时免重复解析）；其他方言退回通用 JSON
JsonDict = JSON().with_variant(JSONB(), "postgresql")


def dump_message(message: ModelMessage) -> dict[str, Any]:
    dumped = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    result: dict[str, Any] = dumped
    return result


def load_message(raw: dict[str, Any]) -> ModelMessage:
    return ModelMessagesTypeAdapter.validate_python([raw])[0]


class PydanticJson(TypeDecorator[Any]):
    """JSONB <-> Pydantic 模型或 TypeAdapter（含 discriminated union）。"""

    impl = JsonDict
    cache_ok = True

    def __init__(self, model: type[BaseModel] | TypeAdapter[Any]) -> None:
        super().__init__()
        self.adapter = model if isinstance(model, TypeAdapter) else TypeAdapter(model)

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self.adapter.dump_python(value, mode="json", exclude_none=True)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self.adapter.validate_python(value)
