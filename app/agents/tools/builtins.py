"""BaseAgent 内置的函数工具。"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import ModelRetry

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def get_current_time(timezone: str | None = None) -> dict[str, str]:
    """查询当前日期与时间，结果带时区与星期。

    Args:
        timezone: IANA 时区名，例如 Asia/Shanghai、UTC；留空表示服务器本地时区。
    """
    utc = datetime.now(UTC)
    try:
        now = datetime.now(ZoneInfo(timezone)) if timezone else datetime.now().astimezone()
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ModelRetry(
            f"无法识别时区 {timezone!r}，请使用 IANA 名称，例如 Asia/Shanghai 或 UTC。"
        ) from error

    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "clock": now.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS[now.weekday()],
        "timezone": now.tzname() or "UTC",
        "utc_offset": now.strftime("%z"),
        "utc": utc.isoformat(timespec="seconds"),
    }
