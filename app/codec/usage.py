"""token 用量的归一与增量计算。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai import RunUsage
from pydantic_ai.messages import ModelMessage

from app.codec.content import to_json_value
from app.domain.run_items import TokenUsage


def usage_delta(total: TokenUsage, prior: TokenUsage | None) -> TokenUsage:
    """AgentRunResult.usage 含历史 seed，本 run 只记差值。"""
    if prior is None:
        return total
    data = {
        field: max(0, getattr(total, field) - getattr(prior, field))
        for field in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    }
    data["total_tokens"] = data["input_tokens"] + data["output_tokens"]
    return TokenUsage.model_validate(data)


def token_usage(usage: Any) -> TokenUsage | None:
    if usage is None:
        return None
    dotted = to_json_value(usage)
    if not isinstance(dotted, dict):
        return None
    converted = TokenUsage.model_validate(
        {key: value for key, value in dotted.items() if value is not None}
    )
    if converted.has_values() and not converted.requests:
        converted.requests = 1
    return converted if converted.has_values() else None


def sum_usage(messages: Sequence[ModelMessage]) -> RunUsage:
    """把历史里每条 ModelResponse 的 usage 累加回 Conversation，让预算跨轮延续。"""
    usage = RunUsage()
    for message in messages:
        item = getattr(message, "usage", None)
        if item is not None:
            usage += item
            usage.requests += 1
    return usage
