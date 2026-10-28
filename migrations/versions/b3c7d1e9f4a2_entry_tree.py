"""entry log becomes a tree: parent_entry_id + active leaf, interrupts move onto entries

Revision ID: b3c7d1e9f4a2
Revises: f2b6d0a4c9e1
Create Date: 2026-10-25 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c7d1e9f4a2"
down_revision: str | Sequence[str] | None = "f2b6d0a4c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_entries",
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        "ck_session_entries_no_self_parent",
        "session_entries",
        "parent_entry_id <> id",
    )
    op.create_foreign_key(
        "fk_session_entries_parent_entry_id",
        "session_entries",
        "session_entries",
        ["parent_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_session_entries_parent", "session_entries", ["session_id", "parent_entry_id"]
    )

    op.add_column(
        "sessions",
        sa.Column("active_leaf_entry_id", sa.Uuid(), nullable=True),
    )
    # active_leaf_entry_id 不建外键：sessions ↔ session_entries 互引会让 SQLite 建/删表失败
    # 未决中断改挂在产生它的 entry 上，会话行不再需要这一列
    op.drop_column("sessions", "pending_interrupts")
    op.execute("UPDATE sessions SET format_version = 4")
    op.alter_column("sessions", "format_version", server_default=sa.text("4"))


def downgrade() -> None:
    op.drop_column("sessions", "active_leaf_entry_id")
    op.add_column(
        "sessions",
        sa.Column(
            "pending_interrupts",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.execute("UPDATE sessions SET format_version = 3, pending_interrupts = '[]'")
    op.alter_column("sessions", "format_version", server_default=sa.text("3"))

    op.drop_index("ix_session_entries_parent", table_name="session_entries")
    op.drop_constraint(
        "fk_session_entries_parent_entry_id", "session_entries", type_="foreignkey"
    )
    op.drop_constraint("ck_session_entries_no_self_parent", "session_entries", type_="check")
    op.drop_column("session_entries", "parent_entry_id")
