"""绑定会话的 run 存储门面：读上下文、追加 Item。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.enums import RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run_item import RunItem, TokenUsage
from app.services import item_codec
from app.services import session_run as run_service


class SessionStore:
    def __init__(
        self,
        session: AsyncSession,
        session_id: UUID,
        model_id: int | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.session = session
        # 每次写入独立 session，避免和 agent 运行/外层请求共用同一事务；
        # 直接测试没有传 factory 时从 bind 派生一个。
        if session_factory is None:
            bind = session.bind
            if isinstance(bind, AsyncEngine):
                session_factory = async_sessionmaker(bind, expire_on_commit=False)
        self.session_factory = session_factory
        self.session_id = session_id
        self.model_id = model_id
        self._run_id_fixed = run_id is not None
        self.run_id = run_id or str(uuid4())
        self._run_ready = False

    def begin_run(self) -> None:
        """直接对话的下一次 turn 需要新的 run_id；HTTP run 的 id 是固定的。"""
        if not self._run_id_fixed:
            self.run_id = str(uuid4())
        self._run_ready = False

    @property
    def run_uuid(self) -> UUID:
        return UUID(self.run_id)

    @asynccontextmanager
    async def db(self) -> AsyncIterator[AsyncSession]:
        """每次写入独立 session，避免和 agent 运行/外层请求共用同一事务。"""
        if self.session_factory is None:
            yield self.session
            return
        async with self.session_factory() as session:
            yield session

    async def ensure_run(self, user_input: str | None = None) -> None:
        """HTTP 已经建好 run；直接对话在这里懒建。"""
        if self._run_ready:
            return
        async with self.db() as db:
            existing = await db.get(SessionRun, self.run_uuid)
            if existing is None:
                chat_session = await db.get(ChatSession, self.session_id)
                await run_service.create_run(
                    db,
                    self.session_id,
                    run_id=self.run_uuid,
                    content=(
                        item_codec.user_items_from_text(user_input)
                        if user_input is not None
                        else []
                    ),
                    parent_run_id=chat_session.active_leaf_run_id if chat_session else None,
                    model_id=self.model_id,
                )
        self._run_ready = True

    async def load(self) -> list[ModelMessage]:
        async with self.db() as db:
            return (await run_service.build_context(db, self.session_id)).messages

    async def append_items(
        self, items: Sequence[RunItem], *, usage: TokenUsage | None = None
    ) -> list[RunItem]:
        await self.ensure_run()
        async with self.db() as db:
            await run_service.append_items(db, self.session_id, self.run_uuid, items, usage=usage)
        return list(items)

    async def set_status(self, status: RunStatus) -> None:
        async with self.db() as db:
            await run_service.set_run_status(db, self.session_id, self.run_uuid, status)
