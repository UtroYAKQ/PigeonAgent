"""run 域的数据结构与运行流程共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage

from app.domain.run_items import PendingInterrupts
from app.models.session_run import SessionRun


@dataclass(slots=True)
class ResumeDecisions:
    interrupt_id: UUID
    approvals: dict[str, bool] = field(default_factory=dict)
    calls: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingBatch:
    run_id: UUID
    run_seq: int
    interrupt_id: UUID
    interrupts: PendingInterrupts


@dataclass(slots=True)
class BuiltContext:
    runs: list[SessionRun]
    messages: list[ModelMessage]
    pending: list[PendingBatch] = field(default_factory=list)
