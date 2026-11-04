"""linear entry log: 6 entry types, no tree, session-level pending interrupts

Revision ID: f2b6d0a4c9e1
Revises: e9a1c2d3f4b5
Create Date: 2026-10-25 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b6d0a4c9e1"
down_revision: str | Sequence[str] | None = "e9a1c2d3f4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres 用 JSONB，其他方言退回通用 JSON
JsonDict = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.drop_table("session_entries")

    op.drop_column("sessions", "active_leaf_entry_id")
    op.drop_column("sessions", "pending_entry_id")
    op.drop_column("sessions", "pending_requests")
    op.add_column(
        "sessions",
        sa.Column(
            "pending_interrupts",
            JsonDict,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    # 会话级 token 累计：汇总时不必回读整份日志
    op.add_column(
        "sessions",
        sa.Column("usage", JsonDict, nullable=False, server_default=sa.text("'{}'")),
    )
    # run 租约到期时间，崩掉的 worker 不会永久锁住会话
    op.add_column(
        "sessions",
        sa.Column("active_run_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE sessions SET format_version = 3, entry_seq = 0, "
        "active_run_id = NULL, pending_interrupts = '[]', usage = '{}'"
    )
    op.alter_column("sessions", "format_version", server_default=sa.text("3"))

    op.create_table(
        "session_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", JsonDict, nullable=False),
        sa.Column("interrupt_id", sa.Uuid(), nullable=True),
        # 反范式检索列：消息正文 / 工具名 / 摘要，供会话内搜索用
        sa.Column(
            "search_text",
            sa.String(length=2000),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_entries_session_id_seq"),
        # 一个中断批次每类决策最多一条（approval 和 call 可以同批并存）
        sa.UniqueConstraint(
            "session_id", "interrupt_id", "type", name="uq_session_entries_session_interrupt"
        ),
    )
    op.create_index("ix_session_entries_type_seq", "session_entries", ["session_id", "type", "seq"])


def downgrade() -> None:
    op.drop_index("ix_session_entries_type_seq", table_name="session_entries")
    op.drop_table("session_entries")

    op.drop_column("sessions", "active_run_expires_at")
    op.drop_column("sessions", "usage")
    op.drop_column("sessions", "pending_interrupts")
    op.add_column("sessions", sa.Column("pending_requests", JsonDict, nullable=True))
    op.add_column("sessions", sa.Column("pending_entry_id", sa.Uuid(), nullable=True))
    op.add_column("sessions", sa.Column("active_leaf_entry_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE sessions SET format_version = 2, active_run_id = NULL")
    op.alter_column("sessions", "format_version", server_default=sa.text("2"))

    op.create_table(
        "session_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", JsonDict, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("parent_entry_id <> id", name="ck_session_entries_no_self_parent"),
        sa.ForeignKeyConstraint(["parent_entry_id"], ["session_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_entries_session_id_seq"),
    )
    op.create_index(
        "ix_session_entries_parent_seq",
        "session_entries",
        ["session_id", "parent_entry_id", "seq"],
    )
    op.create_index("ix_session_entries_type", "session_entries", ["session_id", "type"])
