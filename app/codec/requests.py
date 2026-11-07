"""一次 DeferredToolRequests 到中断 item 的转换。"""

from __future__ import annotations

from uuid import uuid4

from pydantic_ai import DeferredToolRequests

from app.domain.run_items import ApprovalRequestItem, CallRequestItem, RunItem


def to_request_items(requests: DeferredToolRequests) -> list[RunItem]:
    """一次 DeferredToolRequests 的审批与 Call 共用同一个 interrupt_id，各自成一条批量 item。"""
    batch_id = uuid4()
    items: list[RunItem] = []
    if requests.approvals:
        items.append(
            ApprovalRequestItem(
                interrupt_id=batch_id,
                tool_call_ids=[call.tool_call_id for call in requests.approvals],
            )
        )
    if requests.calls:
        metadata = {
            call_id: value
            for call_id, value in requests.metadata.items()
            if call_id in {call.tool_call_id for call in requests.calls}
        }
        items.append(
            CallRequestItem(
                interrupt_id=batch_id,
                tool_call_ids=[call.tool_call_id for call in requests.calls],
                metadata=metadata or None,
            )
        )
    return items
