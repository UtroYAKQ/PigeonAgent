"""时间归一化：naive 按 UTC 解释，aware 换算到 UTC。"""

from datetime import UTC, datetime, timedelta, timezone

from app.domain.time import ensure_utc


def test_naive_is_treated_as_utc() -> None:
    value = datetime(2026, 1, 2, 3, 4, 5)
    assert ensure_utc(value) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_aware_is_converted_without_changing_the_instant() -> None:
    value = datetime(2026, 1, 2, 11, 4, 5, tzinfo=timezone(timedelta(hours=8)))
    assert ensure_utc(value) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
