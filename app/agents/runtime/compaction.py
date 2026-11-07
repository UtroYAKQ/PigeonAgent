"""上下文压缩：把已有历史摘要成一段可回放的系统上下文。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, CancellationToken
from pydantic_ai.messages import BinaryContent, FileUrl, ModelMessage
from pydantic_ai.models import Model

from app import codec
from app.domain.run_items import TokenUsage

COMPACTION_INSTRUCTIONS = """\
你是上下文压缩器。请把提供的历史对话压缩成一份供后续回合继续工作的摘要。

要求：
- 保留用户的目标、约束、偏好和已经确认的决定；
- 保留关键事实、数据、路径、标识符、代码或命令要点，以及工具结果里的重要信息；
- 记录已完成的操作、遇到的问题、失败原因和下一步待办；
- 不要编造历史中没有出现的信息，不要写寒暄，也不要解释摘要过程；
- 用简洁的中文条目输出，总长度控制在 1200 字以内。"""

SUMMARY_REQUEST = "请压缩以上对话历史，输出后续回合可以继续使用的摘要。"


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    summary: str
    usage: TokenUsage | None


def _value_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        # 中文约 1 字 1 token，英文约 4 字符 1 token，折中按 3 字符估
        return max(1, len(value) // 3)
    if isinstance(value, BinaryContent):
        return 1024
    if isinstance(value, FileUrl):
        return 16
    if isinstance(value, (list, tuple)):
        return sum(_value_tokens(item) for item in value)
    if isinstance(value, dict):
        return sum(_value_tokens(key) + _value_tokens(item) for key, item in value.items())
    if isinstance(value, (int, float, bool)):
        return 4
    return max(1, len(str(value)) // 4)


def estimate_tokens(messages: Sequence[ModelMessage]) -> int:
    """够用的上下文体积估算；只用来决定是否压缩，不追求 tokenizer 精度。"""
    total = 0
    for message in messages:
        total += 6
        for part in message.parts:
            total += _value_tokens(getattr(part, "content", None))
            total += _value_tokens(getattr(part, "args", None))
            total += _value_tokens(getattr(part, "tool_name", None))
            total += _value_tokens(getattr(part, "tool_call_id", None))
    return total


async def summarize(
    model: Model,
    messages: Sequence[ModelMessage],
    *,
    cancellation_token: CancellationToken | None = None,
) -> CompactionSummary:
    """用同一个模型把历史压成摘要；摘要调用的用量单独返回用于落账。"""
    agent = Agent(
        model,
        name="context-compaction",
        instructions=COMPACTION_INSTRUCTIONS,
        output_type=str,
    )
    result = await agent.run(
        SUMMARY_REQUEST,
        message_history=list(messages),
        cancellation_token=cancellation_token,
    )
    summary = str(result.output).strip()
    return CompactionSummary(summary=summary, usage=codec.token_usage(result.usage))
