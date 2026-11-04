"""drop legacy session_entry fields

- interrupted 状态归一为 complete（pending 由 payload 表达）
- 删除不再使用的 in_context / depth / target_entry_id

Revision ID: d8f3a1c2b4e6
Revises: c5e8f0b2d3a4
Create Date: 2026-10-25 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f3a1c2b4e6"
down_revision: Union[str, Sequence[str], None] = "c5e8f0b2d3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE session_entries SET status = 'complete' WHERE status = 'interrupted'")
    # target_entry_id 在外键定义里，SQLite 的裸 ALTER DROP COLUMN 处理不了，走 batch 重建表
    with op.batch_alter_table("session_entries") as batch:
        batch.drop_column("target_entry_id")
        batch.drop_column("depth")
        batch.drop_column("in_context")


def downgrade() -> None:
    op.add_column(
        "session_entries",
        sa.Column(
            "in_context",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "session_entries",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "session_entries",
        sa.Column(
            "target_entry_id",
            sa.Uuid(),
            sa.ForeignKey("session_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
