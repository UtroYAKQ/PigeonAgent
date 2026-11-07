"""字符串到 UUID 的统一解析。"""

from __future__ import annotations

from uuid import UUID


def parse_uuid(value: str | UUID) -> UUID | None:
    """解析失败返回 None，由调用方决定报错方式。"""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except ValueError:
        return None
