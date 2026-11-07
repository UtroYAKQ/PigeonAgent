"""上下文拼接：从最近压缩点之后重建模型消息。"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import codec
from app.domain.run_items import CompactionItem, ImageItem, RunItem, ToolResultItem, VideoItem
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services import file_service
from app.services.run.pending import pending_batches_from_path
from app.services.run.tree import load_by_ids, path_ids
from app.services.run.types import BuiltContext


def _compaction_start(runs: Sequence[SessionRun]) -> tuple[int, int] | None:
    """自底向上找最近的压缩节点，返回 (run 下标, 该 run 内最后一个压缩 Item 下标)。"""
    for run_index in range(len(runs) - 1, -1, -1):
        run = runs[run_index]
        if not run.compacted:
            continue
        for item_index in range(len(run.content) - 1, -1, -1):
            if isinstance(run.content[item_index], CompactionItem):
                return run_index, item_index
        # 标记在但 Item 丢了：保守地从这一 run 的开头算起，宁可多带不可漏带
        return run_index, 0
    return None


async def _load_context_tail(db: AsyncSession, session_id: UUID, leaf_id: UUID) -> list[SessionRun]:
    """只载入最近压缩点及其之后的 run；更早的 content 已压缩，不必反序列化。"""
    ids = await path_ids(db, session_id, leaf_id)
    if not ids:
        return []
    compacted_ids = set(
        (
            await db.scalars(
                select(SessionRun.id).where(SessionRun.id.in_(ids), SessionRun.compacted.is_(True))
            )
        ).all()
    )
    start = max(
        (index for index, run_id in enumerate(ids) if run_id in compacted_ids),
        default=0,
    )
    return await load_by_ids(db, ids[start:])


async def build_context(
    db: AsyncSession,
    session_id: UUID,
    *,
    leaf_id: UUID | None = None,
    with_media: bool = True,
) -> BuiltContext:
    chat_session = await db.get(ChatSession, session_id)
    leaf = (
        leaf_id
        if leaf_id is not None
        else (chat_session.active_leaf_run_id if chat_session is not None else None)
    )
    if leaf is None:
        return BuiltContext(runs=[], messages=[])
    runs = await _load_context_tail(db, session_id, leaf)
    first_items: Sequence[RunItem] | None = None
    start = _compaction_start(runs)
    if start is not None:
        run_index, item_index = start
        runs = runs[run_index:]
        first_items = runs[0].content[item_index:]
    # 未决批次就在这条路径上，别再按会话重走一遍 path_ids
    pending = pending_batches_from_path(runs)
    skip = {item.tool_call_id for batch in pending for item in batch.interrupts}
    messages: list[ModelMessage] = []
    slices = [
        (run, first_items if index == 0 and first_items is not None else run.content)
        for index, run in enumerate(runs)
    ]
    # 只有会进上下文的媒体才取字节；展示用的生成图不要每轮白下载一遍。
    # 读图工具的结果把 base64 剥成了 media 引用，也在这里按 file_id 取回来。
    media_ids: list[str] = []
    for _, items in slices:
        for item in items:
            if not item.in_context:
                continue
            if isinstance(item, (ImageItem, VideoItem)) and item.file_id:
                media_ids.append(item.file_id)
            elif isinstance(item, ToolResultItem):
                media_ids.extend(ref.file_id for ref in item.media)
    media = await file_service.load_media(db, media_ids) if with_media else {}
    for run, items in slices:
        messages.extend(codec.messages_from_items(items, usage=run.usage, media=media))
    messages = codec.repair_dangling_tool_calls(messages, skip_tool_call_ids=skip)
    return BuiltContext(runs=runs, messages=messages, pending=pending)
