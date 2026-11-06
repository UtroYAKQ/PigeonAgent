"""绑定会话的 run 存储门面：读上下文、追加 Item。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import codec
from app.core.exceptions import CreditsExhausted
from app.domain.run_items import CompactionItem, RunItem, TokenUsage
from app.enums import RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services import run_store

logger = logging.getLogger(__name__)

# 用量观察者：每次带用量的落库成功后被调用。收积分、限额这些副作用
# 由注入方决定，存储层不认识它们。
UsageObserver = Callable[[TokenUsage], Awaitable[None]]


class SessionStore:
    def __init__(
        self,
        db: AsyncSession,
        session_id: UUID,
        model_id: int | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        run_id: str | None = None,
        on_usage: UsageObserver | None = None,
    ) -> None:
        self._fallback_db = db
        # 每次写入都单开一条数据库连接，避免和 agent 运行/外层请求共用同一事务；
        # 直接测试没有传 factory 时从 bind 派生一个。
        if session_factory is None:
            bind = db.bind
            if isinstance(bind, AsyncEngine):
                session_factory = async_sessionmaker(bind, expire_on_commit=False)
        self.session_factory = session_factory
        self.session_id = session_id
        self.model_id = model_id
        self._run_id_fixed = run_id is not None
        self.run_id = run_id or str(uuid4())
        self._run_ready = False
        self._current_run: SessionRun | None = None
        # 一轮内先攒 item，普通文本/思考按批提交；请求、工具结果和收尾强制落库
        self._buffer_items: list[RunItem] = []
        self._buffer_usage: TokenUsage | None = None
        self._flush_lock = asyncio.Lock()
        self._on_usage = on_usage

    def begin_run(self) -> None:
        """直接对话的下一次 turn 需要新的 run_id；HTTP run 的 id 是固定的。"""
        if not self._run_id_fixed:
            self.run_id = str(uuid4())
        self._run_ready = False
        self._current_run = None

    @property
    def run_uuid(self) -> UUID:
        return UUID(self.run_id)

    @asynccontextmanager
    async def db(self) -> AsyncIterator[AsyncSession]:
        """每次写入都单开一条数据库连接，避免和 agent 运行/外层请求共用同一事务。"""
        if self.session_factory is None:
            yield self._fallback_db
            return
        async with self.session_factory() as fresh_db:
            yield fresh_db

    async def ensure_run(self, user_input: str | None = None) -> SessionRun:
        """HTTP 已经建好 run；直接对话在这里懒建。"""
        if self._run_ready and self._current_run is not None:
            return self._current_run
        await self.flush()
        async with self.db() as db:
            existing = await db.get(SessionRun, self.run_uuid)
            if existing is None:
                chat_session = await db.get(ChatSession, self.session_id)
                run = await run_store.create_run(
                    db,
                    self.session_id,
                    run_id=self.run_uuid,
                    content=(
                        codec.user_items_from_text(user_input) if user_input is not None else []
                    ),
                    parent_run_id=chat_session.active_leaf_run_id if chat_session else None,
                    model_id=self.model_id,
                )
            else:
                run = existing
        self._run_ready = True
        self._current_run = run
        return run

    async def load_context(self, leaf_id: UUID | None = None) -> run_store.BuiltContext:
        await self.flush()
        async with self.db() as db:
            return await run_store.build_context(db, self.session_id, leaf_id=leaf_id)

    async def load(self) -> list[ModelMessage]:
        return (await self.load_context()).messages

    async def append_items(
        self, items: Sequence[RunItem], *, usage: TokenUsage | None = None
    ) -> list[RunItem]:
        await self.ensure_run()
        self._buffer_items.extend(items)
        if usage is not None and usage.has_values():
            self._buffer_usage = (
                usage if self._buffer_usage is None else self._buffer_usage.merged(usage)
            )
        # 中断请求、工具结果和错误是状态边界，不能攒到下一批
        boundary = any(
            item.type in {"approval_request", "call_request", "tool_result", "error"}
            for item in items
        )
        if boundary or len(self._buffer_items) >= 16 or (usage is not None and usage.has_values()):
            await self.flush()
        return list(items)

    async def flush(self) -> None:
        async with self._flush_lock:
            items = self._buffer_items
            usage = self._buffer_usage
            if not items and usage is None:
                return
            self._buffer_items = []
            self._buffer_usage = None
            try:
                async with self.db() as db:
                    await run_store.append_items(
                        db, self.session_id, self.run_uuid, items, usage=usage
                    )
            except Exception:
                # 写失败把内容放回去，调用方还能在收尾时再试一次
                self._buffer_items = [*items, *self._buffer_items]
                if usage is not None:
                    self._buffer_usage = (
                        usage if self._buffer_usage is None else usage.merged(self._buffer_usage)
                    )
                raise
            if usage is not None and usage.has_values():
                await self._notify_usage(usage)

    async def _notify_usage(self, usage: TokenUsage) -> None:
        """通知用量观察者（计费等）；观察者查库失败不能打断对话本身。

        但观察者决定「本轮该停」时要把信号放行：那是运行控制，交给 AgentTurn
        归类成一条带原因的失败落进 run 历史，而不是在这里悄悄吞掉。
        """
        if self._on_usage is None:
            return
        try:
            await self._on_usage(usage)
        except CreditsExhausted:
            raise
        except Exception:
            logger.exception("Usage observer failed for run %s", self.run_id)

    async def record_compaction(
        self, item: CompactionItem, *, usage: TokenUsage | None = None
    ) -> None:
        await self.ensure_run()
        await self.flush()
        async with self.db() as db:
            await run_store.record_compaction(db, self.session_id, self.run_uuid, item, usage=usage)
        if usage is not None and usage.has_values():
            await self._notify_usage(usage)

    async def set_status(self, status: RunStatus) -> None:
        await self.flush()
        async with self.db() as db:
            await run_store.set_run_status(db, self.session_id, self.run_uuid, status)
