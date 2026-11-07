"""/usage/me 的聚合已下推到 SQL：守住 UTC 日分桶、今日/本月小计、模型排序与最近条数。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.run_items import TokenUsage
from app.models.chat.log import ChatRequestLog
from tests.conftest import TEST_USER_ID


def add_log(
    db_session: AsyncSession,
    moment: datetime,
    *,
    model: str,
    tokens: int,
    cache_read: int = 0,
    credits: float = 0.0,
) -> None:
    db_session.add(
        ChatRequestLog(
            id=uuid4(),
            user_id=TEST_USER_ID,
            model_name=model,
            status="completed",
            usage=TokenUsage(
                requests=1,
                input_tokens=tokens,
                cache_read_tokens=cache_read,
            ),
            credits_charged=credits,
            created_at=moment,
        )
    )


async def test_daily_buckets_follow_utc_days(client: AsyncClient, db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    # 00:30 与 23:30 同属一个 UTC 日；机器时区是东八区时，按本地时间分桶会串到隔壁天
    morning = now.replace(hour=0, minute=30, second=0, microsecond=0)
    evening = now.replace(hour=23, minute=30, second=0, microsecond=0)
    yesterday = morning - timedelta(days=1)

    add_log(db_session, morning, model="gpt-mini", tokens=100, cache_read=10, credits=1.5)
    add_log(db_session, evening, model="gpt-max", tokens=200, credits=0.5)
    add_log(db_session, yesterday, model="gpt-mini", tokens=50, cache_read=5, credits=0.25)
    await db_session.commit()

    body = (await client.get("/api/v1/usage/me")).json()
    daily = {row["date"]: row for row in body["daily"]}
    today_key = now.date().isoformat()
    yesterday_key = yesterday.date().isoformat()

    assert daily[today_key] == {
        "date": today_key,
        "tokens": 300,
        "credits": 2.0,
        "runs": 2,
        "cache_read_tokens": 10,
    }
    assert daily[yesterday_key]["tokens"] == 50
    assert daily[yesterday_key]["runs"] == 1

    totals = body["totals"]
    assert totals["runs_total"] == 3
    assert totals["today_tokens"] == 300
    assert totals["today_cache_read_tokens"] == 10
    assert totals["today_credits"] == 2.0

    # 昨天若已跨月，那 50 个 token 就不该算进本月
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    expected_month = 350 if yesterday >= month_start else 300
    assert totals["month_tokens"] == expected_month
    assert totals["month_runs"] == (3 if yesterday >= month_start else 2)
    assert totals["range_input_tokens"] == 350
    assert totals["range_output_tokens"] == 0
    assert totals["range_cache_read_tokens"] == 15
    assert totals["range_credits"] == 2.25

    assert [row["model_name"] for row in body["by_model"]] == ["gpt-max", "gpt-mini"]
    assert body["by_model"][1]["tokens"] == 150


async def test_recent_is_capped_and_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    for index in range(10):
        add_log(
            db_session,
            now - timedelta(minutes=index),
            model="gpt-mini",
            tokens=10 * (index + 1),
        )
    await db_session.commit()

    recent = (await client.get("/api/v1/usage/me")).json()["recent"]

    assert len(recent) == 8
    stamps = [row["created_at"] for row in recent]
    assert stamps == sorted(stamps, reverse=True)
    assert recent[0]["total_tokens"] == 10
