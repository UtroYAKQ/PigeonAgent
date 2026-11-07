"""模型选项：思考挡位与请求参数。"""

from __future__ import annotations

from typing import cast

from pydantic_ai import ModelSettings

from app.models.llm_model import LlmModel


def _supported_thinking_level(record: LlmModel, level: str | None) -> str | None:
    if level is None or level not in record.thinking_levels:
        return None
    return level


def _settings_with_thinking(settings: ModelSettings, thinking_level: str | None) -> ModelSettings:
    if thinking_level is None:
        return settings
    return cast(ModelSettings, {**settings, "thinking": thinking_level})
