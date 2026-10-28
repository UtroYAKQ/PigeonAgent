"""e2b 兼容沙箱的进程内池：生命周期按「沙箱回收策略」执行。

- 正常执行中：保持 active，每次工具活动刷新计时；10 分钟无动静 → kill。
- 审批 / 参数询问中断：pause() 保活并保留 sandbox_id；同一个钟超时 → kill 清空。
- 本轮跑完：立即 kill。用户恢复时 connect() 唤醒，接不上就兜底重建新实例。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import Settings
from app.services.workspace import connect_sandbox, create_sandbox

if TYPE_CHECKING:
    from e2b import AsyncSandbox
else:  # pragma: no cover
    AsyncSandbox = Any

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    sandbox: AsyncSandbox
    sandbox_id: str
    last_touch: float = field(default_factory=time.monotonic)
    paused: bool = False
    run_id: str | None = None


class SandboxPool:
    """按会话独占的沙箱池：多轮 run 复用，中断时挂起，跑完立即回收。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._entries: dict[UUID, _Entry] = {}
        self._lock = asyncio.Lock()
        self._sweeper: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        self._sweeper = asyncio.create_task(self._sweep_loop())

    async def aclose(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        await asyncio.gather(
            *(self._kill_entry(entry) for entry in list(self._entries.values())),
            return_exceptions=True,
        )
        self._entries.clear()

    # ------------------------------------------------------------------ 对外动作
    async def acquire(self, session_id: UUID, run_id: str) -> AsyncSandbox:
        """拿到本轮要说事的沙箱：有就 connect 复用，断线/被回收就兜底重建。"""
        async with self._lock:
            entry = self._entries.get(session_id)
            settings = self.settings
            if entry is not None:
                if entry.paused:
                    try:
                        entry.sandbox = await connect_sandbox(settings, entry.sandbox_id)
                    except Exception:
                        logger.info(
                            "Sandbox %s for session %s is gone; recreating",
                            entry.sandbox_id,
                            session_id,
                        )
                        entry.sandbox = await create_sandbox(settings)
                        entry.sandbox_id = entry.sandbox.sandbox_id
                    entry.paused = False
            else:
                sandbox = await create_sandbox(settings)
                entry = _Entry(sandbox=sandbox, sandbox_id=sandbox.sandbox_id, run_id=run_id)
                self._entries[session_id] = entry
            entry.run_id = run_id
            return entry.sandbox

    def touch(self, session_id: UUID) -> None:
        entry = self._entries.get(session_id)
        if entry is not None:
            entry.last_touch = time.monotonic()

    async def release(self, session_id: UUID) -> None:
        """审批/询问中断：挂起保活，时钟继续；到点由 sweeper 收尸。"""
        entry = self._entries.get(session_id)
        if entry is None:
            return
        pause = getattr(entry.sandbox, "beta_pause", None)
        if callable(pause):
            try:
                await pause()
            except Exception:
                logger.info(
                    "Sandbox %s does not support pause; keeping it warm", entry.sandbox_id
                )
        entry.paused = True

    async def discard(self, session_id: UUID) -> None:
        """本轮结束：立即回收。"""
        entry = self._entries.pop(session_id, None)
        if entry is not None:
            await self._kill_entry(entry)

    # ------------------------------------------------------------------ 内部
    async def _kill_entry(self, entry: _Entry) -> None:
        kill = getattr(entry.sandbox, "kill", None)
        if not callable(kill):
            return
        try:
            await kill()
        except Exception:
            logger.info("Failed to kill sandbox %s", entry.sandbox_id, exc_info=True)

    async def _sweep_loop(self) -> None:
        interval = min(30.0, max(self.settings.sandbox_idle_seconds / 4, 1.0))
        while True:
            await asyncio.sleep(interval)
            cutoff = time.monotonic() - self.settings.sandbox_idle_seconds
            stale = [key for key, entry in self._entries.items() if entry.last_touch < cutoff]
            for session_id in stale:
                entry = self._entries.pop(session_id, None)
                if entry is not None:
                    logger.info("Sandbox %s idle timeout; killing", entry.sandbox_id)
                    await self._kill_entry(entry)
