"""通道预览：只留人可读的正文片段。"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.run_items import RunItem, item_text


def preview_of(items: Sequence[RunItem]) -> str:
    """反范式预览：只留人和内容相关的部分，base64 和工具参数不进。"""
    chunks = [text[:500] for item in items if (text := item_text(item).strip())]
    return " ".join(chunks)[:2000]
