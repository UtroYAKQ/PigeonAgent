from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


def _set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL 允许读写并发；busy_timeout 让短并发写退避重试而不是直接 database is locked
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def enable_sqlite_pragmas(target: AsyncEngine) -> None:
    # SQLite 默认不强制外键，ON DELETE CASCADE 会静默失效
    if target.dialect.name == "sqlite":
        event.listen(target.sync_engine, "connect", _set_sqlite_pragmas)


enable_sqlite_pragmas(engine)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_session_factory


async def close_engine() -> None:
    await engine.dispose()
