"""normalize legacy resource items

Revision ID: f2a6c8d0e4b1
Revises: d3e7a1c9f5b2
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f2a6c8d0e4b1"
down_revision: str | Sequence[str] | None = "d3e7a1c9f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧版 ResourceItem 用 storage_key；现在 FileIdRef 的字段是 file_id，
    # BaseItem 又禁止多余字段，不修历史会导致整条会话无法反序列化。
    op.execute(
        """
        UPDATE session_runs AS r
        SET content = (
            SELECT jsonb_agg(
                CASE
                    WHEN item->>'type' = 'resource' AND item ? 'storage_key'
                    THEN (item - 'storage_key')
                         || jsonb_build_object('file_id', item->>'storage_key')
                    ELSE item
                END
                ORDER BY ordinality
            )
            FROM jsonb_array_elements(r.content) WITH ORDINALITY AS t(item, ordinality)
        )
        WHERE EXISTS (
            SELECT 1
            FROM jsonb_array_elements(r.content) AS item
            WHERE item->>'type' = 'resource' AND item ? 'storage_key'
        )
        """
    )


def downgrade() -> None:
    # 数据迁移无法区分后来写入的合法 file_id，保留现状。
    pass
