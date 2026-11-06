"""时间归一化：SQLite 读回的 DateTime(timezone=True) 可能不带 tz，统一按 UTC 解释。"""

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
