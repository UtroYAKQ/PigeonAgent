"""操作日志的跨层契约：中间件产事件，后台任务负责落库。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings


@dataclass(slots=True)
class OperationEvent:
    request_id: str | None = None
    kind: str = "request"
    actor_id: UUID | None = None
    actor_email: str | None = None
    method: str | None = None
    path: str | None = None
    route: str | None = None
    query: Any = None
    request_body: bytes | None = None
    status_code: int | None = None
    response_body: bytes | None = None
    duration_ms: int | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    request_truncated: bool = False
    response_truncated: bool = False
    client_ip: str | None = None
    user_agent: str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class OperationSink(Protocol):
    """中间件只需要这几项能力，具体队列和写库由任务层实现。"""

    @property
    def settings(self) -> Settings: ...

    @property
    def enabled(self) -> bool: ...

    def should_log(self, path: str) -> bool: ...

    def submit(self, event: OperationEvent) -> None: ...

    def submit_admin(
        self,
        *,
        actor: Any = None,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None: ...
