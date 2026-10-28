"""replace session_entries with the session_runs item tree

Revision ID: d4e6f8a0b2c4
Revises: f6a9b3c2d8e1
Create Date: 2026-10-26 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c4"
down_revision: str | Sequence[str] | None = "f6a9b3c2d8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'running'")
        ),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default=sa.text("'turn'")),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("compacted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("preview", sa.String(length=2000), nullable=False, server_default=sa.text("''")),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_run_id"], ["session_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_runs_session_id_seq"),
        sa.CheckConstraint("parent_run_id <> id", name="ck_session_runs_no_self_parent"),
    )
    op.create_index("ix_session_runs_parent", "session_runs", ["session_id", "parent_run_id"])
    op.create_index("ix_session_runs_status", "session_runs", ["session_id", "status"])
    op.create_index("ix_session_runs_compacted", "session_runs", ["session_id", "compacted", "seq"])

    # 旧树无法无损映射成线性 item run：按约定直接删表，不迁移数据
    op.drop_table("session_entries")

    op.add_column(
        "sessions",
        sa.Column("run_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("sessions", sa.Column("active_leaf_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_last_run_at", "sessions", ["last_run_at"])
    op.execute("UPDATE sessions SET format_version = 5")
    op.alter_column(
        "sessions", "format_version", server_default=sa.text("5"), existing_type=sa.Integer()
    )

    op.drop_index("ix_sessions_last_entry_at", table_name="sessions")
    op.drop_column("sessions", "active_leaf_entry_id")
    op.drop_column("sessions", "entry_seq")
    op.drop_column("sessions", "last_entry_at")

    if op.get_bind().dialect.name == "postgresql":
        for column in ("content", "usage"):
            op.execute(
                f"ALTER TABLE session_runs ALTER COLUMN {column} TYPE JSONB USING {column}::jsonb"
            )


def downgrade() -> None:
    op.create_table(
        "session_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("interrupt_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column(
            "search_text", sa.String(length=2000), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_entry_id"], ["session_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_entries_session_id_seq"),
        sa.UniqueConstraint(
            "session_id", "interrupt_id", "type", name="uq_session_entries_session_interrupt"
        ),
        sa.CheckConstraint("parent_entry_id <> id", name="ck_session_entries_no_self_parent"),
    )
    op.create_index("ix_session_entries_type_seq", "session_entries", ["session_id", "type", "seq"])
    op.create_index(
        "ix_session_entries_interrupt", "session_entries", ["session_id", "interrupt_id"]
    )
    op.create_index(
        "ix_session_entries_parent", "session_entries", ["session_id", "parent_entry_id"]
    )

    op.add_column(
        "sessions",
        sa.Column("entry_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("sessions", sa.Column("active_leaf_entry_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "last_entry_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_last_entry_at", "sessions", ["last_entry_at"])
    op.execute("UPDATE sessions SET format_version = 4")
    op.alter_column(
        "sessions", "format_version", server_default=sa.text("4"), existing_type=sa.Integer()
    )

    op.drop_index("ix_sessions_last_run_at", table_name="sessions")
    op.drop_column("sessions", "active_leaf_run_id")
    op.drop_column("sessions", "run_seq")
    op.drop_column("sessions", "last_run_at")

    op.drop_index("ix_session_runs_compacted", table_name="session_runs")
    op.drop_index("ix_session_runs_status", table_name="session_runs")
    op.drop_index("ix_session_runs_parent", table_name="session_runs")
    op.drop_table("session_runs")
