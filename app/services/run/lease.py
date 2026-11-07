"""run 租约：占用时长、存活判断、续租与启动清扫。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.ids import parse_uuid
from app.domain.time import ensure_utc
from app.enums import RunStatus
from app.models.chat.run import SessionRun
from app.models.chat.session import ChatSession

# worker 崩了会话也不会永久卡住；正常跑着的 run 靠心跳续租
RUN_LEASE_SECONDS = 600


def lease_expires_at(now: datetime) -> datetime:
    """租约到期时刻；占用、被动续租和显式 renew 都从这里算，租约时长只解释一次。"""
    return now + timedelta(seconds=RUN_LEASE_SECONDS)


def is_run_live(chat_session: ChatSession, *, now: datetime | None = None) -> bool:
    if chat_session.active_run_id is None:
        return False
    expires_at = chat_session.active_run_expires_at
    if expires_at is None:
        return True
    return ensure_utc(expires_at) > ensure_utc(now or datetime.now(UTC))


async def finish_run(db: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock_session(db, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_id = None
        chat_session.active_run_expires_at = None
    await db.commit()


async def renew_run_lease(db: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock_session(db, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_expires_at = lease_expires_at(datetime.now(UTC))
    await db.commit()


async def clear_expired_run_leases(db: AsyncSession) -> list[tuple[UUID, str]]:
    """启动清扫：回收已过期的租约，并返回对应的 (session_id, run_id)。

    调用方用返回值顺手清掉 Redis 里的 active/owner 标记，避免 worker 硬崩后
    数据库已放行、事件互斥却还要等 TTL 才解除。
    """
    rows = await db.scalars(select(ChatSession).where(ChatSession.active_run_id.is_not(None)))
    expired = [
        (chat_session.id, chat_session.active_run_id)
        for chat_session in rows
        if not is_run_live(chat_session) and chat_session.active_run_id is not None
    ]
    if expired:
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id.in_([session_id for session_id, _ in expired]))
            .values(active_run_id=None, active_run_expires_at=None)
        )
        # worker 硬崩后 run 行可能还停在 running；启动清扫把它标成失败，
        # 前端/统计不会永远把一条死 run 当成进行中。
        run_ids = [parsed for _, run_id in expired if (parsed := parse_uuid(run_id)) is not None]
        if run_ids:
            await db.execute(
                update(SessionRun)
                .where(
                    SessionRun.id.in_(run_ids),
                    SessionRun.status == RunStatus.RUNNING.value,
                )
                .values(status=RunStatus.FAILED.value)
            )
    await db.commit()
    return expired


async def _lock_session(db: AsyncSession, session_id: UUID) -> ChatSession:
    chat_session = await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id).with_for_update()
    )
    if chat_session is None:
        raise NotFoundError(f"会话 {session_id} 不存在")
    return chat_session
