"""应用自定义的响应事件：压缩、审批/Call 请求与回复、用量、失败。

这些事件进入 pydantic-ai 的原生响应事件流；UI 适配器会把 ui=True 的事件
转成 AG-UI CustomEvent，事件日志则负责把它们落成 run content。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import CustomEvent

from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    ErrorItem,
    TokenUsage,
)
from app.services import item_codec


@dataclass(kw_only=True)
class ApprovalRequestEvent(CustomEvent, ui=False):
    interrupt_id: str
    tool_call_ids: list[str]


@dataclass(kw_only=True)
class CallRequestEvent(CustomEvent, ui=False):
    interrupt_id: str
    tool_call_ids: list[str]
    metadata: dict[str, Any] | None = None


@dataclass(kw_only=True)
class RunUsageEvent(CustomEvent, ui=False):
    usage: TokenUsage


@dataclass(kw_only=True)
class RunFailedEvent(CustomEvent, ui=False):
    error: ErrorItem


@dataclass(kw_only=True)
class RunCancelledEvent(CustomEvent, ui=False):
    """取消信号；半截内容由 AgentTurn 自己按增量累计留痕。"""


def request_events(requests: DeferredToolRequests) -> list[CustomEvent]:
    """请求 item 是唯一事实源，事件只是把同一批请求送进响应事件流。"""
    events: list[CustomEvent] = []
    for item in item_codec.to_request_items(requests):
        if isinstance(item, ApprovalRequestItem):
            events.append(
                ApprovalRequestEvent(
                    interrupt_id=str(item.interrupt_id),
                    tool_call_ids=item.tool_call_ids,
                )
            )
        elif isinstance(item, CallRequestItem):
            events.append(
                CallRequestEvent(
                    interrupt_id=str(item.interrupt_id),
                    tool_call_ids=item.tool_call_ids,
                    metadata=item.metadata,
                )
            )
    return events
