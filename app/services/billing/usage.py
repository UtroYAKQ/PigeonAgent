"""个人用量聚合：余额、按天、按模型和最近对话。

聚合全部下推到 SQL，不把 91 天日志整片读进 Python。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, literal_column, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.types import JsonDict
from app.models.account.user import User
from app.models.chat.log import ChatRequestLog
from app.schemas.billing.usage import (
    UsageDaily,
    UsageModelStat,
    UsageOverview,
    UsageRecent,
    UsageTotals,
)

# 热力图窗口：13 周
DAYS = 91
RECENT_LIMIT = 8
# usage 列被 PydanticJson 包了一层，按原始 JSON 类型取下标才能跨方言生成 ->> / json_extract
_usage = type_coerce(ChatRequestLog.usage, JsonDict)


def _day_key(value: Any) -> str:
    """聚合结果可能是 date（Postgres）、'YYYY-MM-DD' 字符串（SQLite），或带时区的 datetime。"""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _day_column(dialect_name: str) -> Any:
    """按 UTC 日分桶。Postgres 容器时区是 Asia/Shanghai，直接取 date() 会整体偏移一天。"""
    created_at = ChatRequestLog.created_at
    if dialect_name == "postgresql":
        return cast(created_at.op("AT TIME ZONE")(literal_column("'UTC'")), Date)
    # SQLite 存进去的本就是 UTC 墙钟
    return func.date(created_at)


def _usage_value(field: str) -> Any:
    """PydanticJson 不透出 JSON 下标操作，退回原始 JSON 类型取键；
    as_integer 在 Postgres 生成 ->>、在 SQLite 生成 JSON_EXTRACT，两边都能求和。"""
    return _usage[field].as_integer()


def _usage_sum(field: str) -> Any:
    return func.coalesce(func.sum(_usage_value(field)), 0)


def _credits_sum() -> Any:
    return func.coalesce(func.sum(ChatRequestLog.credits_charged), 0.0)


async def overview(db: AsyncSession, *, user: User, settings: Settings) -> UsageOverview:
    now = datetime.now(UTC)
    since = now - timedelta(days=DAYS)
    owned = (ChatRequestLog.user_id == user.id, ChatRequestLog.created_at >= since)
    day = _day_column(db.get_bind().dialect.name)

    daily_rows = (
        await db.execute(
            select(
                day,
                func.count(),
                _usage_sum("total_tokens"),
                _usage_sum("cache_read_tokens"),
                _credits_sum(),
            )
            .where(*owned)
            .group_by(day)
        )
    ).all()
    model_rows = (
        await db.execute(
            select(
                ChatRequestLog.model_name,
                func.count(),
                _usage_sum("total_tokens"),
                _usage_sum("cache_read_tokens"),
                _credits_sum(),
            )
            .where(*owned)
            .group_by(ChatRequestLog.model_name)
        )
    ).all()
    recent_rows = (
        await db.execute(
            select(
                ChatRequestLog.created_at,
                ChatRequestLog.model_name,
                ChatRequestLog.status,
                func.coalesce(_usage_value("total_tokens"), 0),
                func.coalesce(_usage_value("cache_read_tokens"), 0),
                ChatRequestLog.credits_charged,
                ChatRequestLog.images_generated,
            )
            .where(*owned)
            .order_by(ChatRequestLog.created_at.desc())
            .limit(RECENT_LIMIT)
        )
    ).all()
    # 区间汇总给「近 13 周统计」表用；按天表里只有总量和缓存，输入/输出单独求一次
    range_row = (
        await db.execute(
            select(
                _usage_sum("input_tokens"),
                _usage_sum("output_tokens"),
                _usage_sum("cache_read_tokens"),
                _credits_sum(),
            ).where(*owned)
        )
    ).one()

    per_day = {_day_key(row[0]): row for row in daily_rows}
    today_key = _day_key(now)
    month_key = _day_key(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))

    totals = UsageTotals(
        runs_total=sum(int(row[1]) for row in daily_rows),
        range_input_tokens=int(range_row[0]),
        range_output_tokens=int(range_row[1]),
        range_cache_read_tokens=int(range_row[2]),
        range_credits=float(range_row[3]),
    )
    for row in daily_rows:
        key = _day_key(row[0])
        if key == today_key:
            totals.today_tokens += int(row[2])
            totals.today_cache_read_tokens += int(row[3])
            totals.today_credits += float(row[4])
        # ISO 日期字符串可以直接按字典序比较，月初就是本月的第一把钥匙
        if key >= month_key:
            totals.month_tokens += int(row[2])
            totals.month_cache_read_tokens += int(row[3])
            totals.month_credits += float(row[4])
            totals.month_runs += int(row[1])

    # 热力图要一整片连续日期，没数据的天补零
    daily: list[UsageDaily] = []
    for offset in range(DAYS - 1, -1, -1):
        key = _day_key(now - timedelta(days=offset))
        entry = per_day.get(key)
        daily.append(
            UsageDaily(
                date=key,
                tokens=int(entry[2]) if entry else 0,
                credits=round(float(entry[4]), 6) if entry else 0.0,
                runs=int(entry[1]) if entry else 0,
                cache_read_tokens=int(entry[3]) if entry else 0,
            )
        )

    by_model = sorted(
        (
            UsageModelStat(
                model_name=row[0],
                runs=int(row[1]),
                tokens=int(row[2]),
                credits=round(float(row[4]), 6),
                cache_read_tokens=int(row[3]),
            )
            for row in model_rows
        ),
        key=lambda item: item.tokens,
        reverse=True,
    )

    return UsageOverview(
        balance=user.credits_balance,
        billing_enabled=settings.billing_enabled,
        totals=totals,
        daily=daily,
        by_model=by_model,
        recent=[
            UsageRecent(
                created_at=row[0],
                model_name=row[1],
                status=row[2],
                total_tokens=int(row[3] or 0),
                cache_read_tokens=int(row[4] or 0),
                credits_charged=float(row[5]),
                images_generated=int(row[6]),
            )
            for row in recent_rows
        ],
    )
