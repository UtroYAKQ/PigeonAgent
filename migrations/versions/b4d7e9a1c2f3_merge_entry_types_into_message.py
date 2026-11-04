"""merge extra entry types into message

除 message / compaction 外的旧类型统一折算为 message；custom 记录折叠掉
（children 重挂到最近的非 custom 祖先）。

Revision ID: b4d7e9a1c2f3
Revises: f8a2c1b3d5e6
Create Date: 2026-10-25 14:00:00.000000

"""

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d7e9a1c2f3"
down_revision: Union[str, Sequence[str], None] = "f8a2c1b3d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    entries = sa.table(
        "session_entries",
        sa.column("id", sa.Uuid()),
        sa.column("parent_entry_id", sa.Uuid()),
        sa.column("entry_type", sa.String()),
        sa.column("depth", sa.Integer()),
    )
    rows = (
        bind.execute(sa.select(entries.c.id, entries.c.parent_entry_id, entries.c.entry_type))
        .mappings()
        .all()
    )
    parents: dict[Any, Any] = {row["id"]: row["parent_entry_id"] for row in rows}
    custom_ids = {row["id"] for row in rows if row["entry_type"] == "custom"}

    if custom_ids:
        # 旧自定义记录（run 锚点、run_usage、subagent_run）从树里摘掉，
        # 子节点挂到最近的非 custom 祖先，保持历史消息链完整
        for row in rows:
            entry_id = row["id"]
            if entry_id in custom_ids:
                continue
            parent_id = parents[entry_id]
            new_parent = parent_id
            seen: set[Any] = set()
            while new_parent in custom_ids and new_parent not in seen:
                seen.add(new_parent)
                new_parent = parents.get(new_parent)
            if new_parent != parent_id:
                bind.execute(
                    entries.update()
                    .where(entries.c.id == entry_id)
                    .values(parent_entry_id=new_parent)
                )
        bind.execute(entries.delete().where(entries.c.entry_type == "custom"))

    bind.execute(
        entries.update()
        .where(entries.c.entry_type.notin_(("message", "compaction")))
        .values(entry_type="message")
    )

    # 折叠后修正 depth，避免前端/调试看到过期层级
    remaining = bind.execute(sa.select(entries.c.id, entries.c.parent_entry_id)).mappings().all()
    parents = {row["id"]: row["parent_entry_id"] for row in remaining}
    children: dict[Any, list[Any]] = {}
    roots: list[Any] = []
    for entry_id, parent_id in parents.items():
        if parent_id is None or parent_id not in parents:
            roots.append(entry_id)
        else:
            children.setdefault(parent_id, []).append(entry_id)
    queue = [(entry_id, 0) for entry_id in roots]
    while queue:
        entry_id, depth = queue.pop()
        bind.execute(entries.update().where(entries.c.id == entry_id).values(depth=depth))
        queue.extend((child, depth + 1) for child in children.get(entry_id, []))


def downgrade() -> None:
    # custom 记录与原始 entry_type 无法重建，因此不回滚数据
    pass
