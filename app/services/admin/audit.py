"""管理员语义操作：投递到异步操作日志队列，不阻塞业务事务。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.observability.request_context import current_operation_context
from app.models.account.user import User

logger = logging.getLogger(__name__)

CONFIG_UPDATE = "config.update"
MODEL_CREATE = "model.create"
MODEL_UPDATE = "model.update"
MODEL_DELETE = "model.delete"
IMAGE_MODEL_CREATE = "image_model.create"
IMAGE_MODEL_UPDATE = "image_model.update"
IMAGE_MODEL_DELETE = "image_model.delete"
USER_UPDATE = "user.update"
USER_PASSWORD_RESET = "user.password_reset"
USER_CREDIT_ADJUST = "user.credit_adjust"
SESSION_UPDATE = "session.update"


async def record(
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    context = current_operation_context()
    if context is None or context.logger is None:
        # 请求上下文外（脚本或未启动日志器）只留一条本地告警，不影响业务。
        logger.warning("Operation logger unavailable; admin action %s not persisted", action)
        return
    context.logger.submit_admin(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        request_id=context.request_id,
    )
