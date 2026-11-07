"""运行任务与取消令牌的注册表；配置 Redis 后取消信号走跨 worker 广播。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai import CancellationToken

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.services.run.control import RunControl

logger = logging.getLogger(__name__)


@dataclass
class RunRegistry:
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    cancellations: dict[str, tuple[UUID, CancellationToken]] = field(default_factory=dict)
    control: RunControl | None = None
    _started: bool = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self.control is not None:
            self.control.set_handler(self._cancel_local)
            self.control.set_ready_handler(self._reconcile_cancels)
            await self.control.start()

    async def wait_ready(self, seconds: float = 2.0) -> None:
        if self.control is not None:
            await self.control.wait_ready(seconds)

    def schedule(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def register(
        self, run_id: str, session_id: UUID, cancellation: CancellationToken
    ) -> None:
        self.cancellations[run_id] = (session_id, cancellation)
        if self.control is None:
            return
        await self.control.register(run_id, session_id)
        try:
            # 取消可能恰好发生在注册令牌之前：listener 那时看不到本地 token，
            # 注册完再补查一次 durable 标记，避免这个极窄窗口漏取消。
            if await self.control.is_cancel_requested(run_id):
                cancellation.cancel()
                logger.info("Run %s cancelled from an early durable flag", run_id)
        except Exception:
            logger.exception("Failed to reconcile early cancel flag for run %s", run_id)

    async def unregister(self, run_id: str) -> None:
        self.cancellations.pop(run_id, None)
        if self.control is not None:
            await self.control.unregister(run_id)

    async def cancel_run(self, session_id: UUID, run_id: str) -> None:
        local = self.cancellations.get(run_id)
        if local is not None:
            if local[0] != session_id:
                raise NotFoundError(f"轮次 {run_id} 不在运行中")
            local[1].cancel()
            return
        if self.control is None:
            raise NotFoundError(f"轮次 {run_id} 不在运行中")
        try:
            handled = await self.control.request_cancel(session_id, run_id)
        except Exception as exc:
            logger.exception("Run control cancel request failed for %s", run_id)
            raise ServiceUnavailableError("取消通道暂时不可用，请稍后重试") from exc
        if not handled:
            raise NotFoundError(f"轮次 {run_id} 不在运行中")

    async def touch(self, run_id: str) -> None:
        local = self.cancellations.get(run_id)
        if local is not None and self.control is not None:
            await self.control.touch(run_id, local[0])

    async def cancel_all(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        run_ids = list(self.cancellations)
        if run_ids:
            await asyncio.gather(*(self.unregister(run_id) for run_id in run_ids))

    async def aclose(self) -> None:
        await self.cancel_all()
        if self.control is not None:
            await self.control.aclose()

    def _cancel_local(self, run_id: str, session_id: UUID) -> None:
        local = self.cancellations.get(run_id)
        if local is not None and local[0] == session_id:
            local[1].cancel()
            logger.info("Run %s cancelled from another worker", run_id)

    async def _reconcile_cancels(self) -> None:
        """listener 重连后补查取消标记，捞回断线期间丢掉的 Pub/Sub 消息。"""
        control = self.control
        if control is None:
            return
        for run_id, (_session_id, token) in list(self.cancellations.items()):
            try:
                requested = await control.is_cancel_requested(run_id)
            except Exception:
                logger.exception("Failed to reconcile cancel flag for run %s", run_id)
                continue
            if requested:
                token.cancel()
                logger.info("Run %s cancelled from a durable cancel flag", run_id)
