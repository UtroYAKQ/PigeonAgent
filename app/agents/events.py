"""应用自定义的响应事件：压缩、审批/Call 请求与回复、用量、失败。

这些事件进入 pydantic-ai 的原生响应事件流；UI 适配器会把 ui=True 的事件
转成 AG-UI CustomEvent，事件日志则负责把它们落成 run content。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import CustomEvent

from app import codec
from app.domain.run_items import (
    ApprovalRequestItem,
    CallRequestItem,
    ErrorItem,
    TokenUsage,
)


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
class CompactionStartEvent(CustomEvent):
    """压缩开始：只给前端画 checkpointer，不落 Item。"""

    estimated_tokens: int = 0
    context_window: int | None = None


@dataclass(kw_only=True)
class CompactionResultEvent(CustomEvent):
    """压缩结果：turn 收到后落成 CompactionItem，并标记目标 run。"""

    summary: str
    tokens_before: int = 0
    items_compacted: int = 0
    # 摘要调用自己的 token 用量；不进 UI payload，只用于落账
    usage: TokenUsage | None = None

    def to_payload(self) -> Any:
        return {
            "summary": self.summary,
            "tokens_before": self.tokens_before,
            "items_compacted": self.items_compacted,
        }


@dataclass(kw_only=True)
class ArtifactEvent(CustomEvent):
    """一张生成好的产物。

    入库和推送分开：Item 决定它在 run.content 里的位置（回放与分支都靠它），
    这个事件只负责让前端在流式阶段立刻把图渲染出来，不用等 run 结束。
    """

    media: list[dict[str, Any]]


@dataclass(kw_only=True)
class RunUsageEvent(CustomEvent):
    """本轮累计用量。

    要和别的内部事件不同地发给前端：正在生成的那条 run 还没落库，
    不给实时用量的话，回答底部的 token 读数会一直显示 0，直到流结束刷新才对上。
    """

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
    for item in codec.to_request_items(requests):
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
