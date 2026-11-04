"""switch session entries to pi's append-only model

Revision ID: e9a1c2d3f4b5
Revises: d8f3a1c2b4e6
Create Date: 2026-10-25 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9a1c2d3f4b5"
down_revision: str | Sequence[str] | None = "d8f3a1c2b4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("session_entries")

    op.add_column("sessions", sa.Column("pending_requests", postgresql.JSONB(), nullable=True))
    op.add_column("sessions", sa.Column("pending_entry_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE sessions SET format_version = 2, active_leaf_entry_id = NULL, "
        "entry_seq = 0, active_run_id = NULL, pending_requests = NULL, pending_entry_id = NULL"
    )
    op.alter_column("sessions", "format_version", server_default=sa.text("2"))

    op.create_table(
        "session_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
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


def downgrade() -> None:
    op.drop_index("ix_session_entries_type", table_name="session_entries")
    op.drop_index("ix_session_entries_parent_seq", table_name="session_entries")
    op.drop_table("session_entries")

    op.drop_column("sessions", "pending_entry_id")
    op.drop_column("sessions", "pending_requests")
    op.execute("UPDATE sessions SET format_version = 1")
    op.alter_column("sessions", "format_version", server_default=sa.text("1"))

    op.create_table(
        "session_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("display", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'complete'"),
            nullable=False,
        ),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("first_kept_entry_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("run_seq", sa.BigInteger(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("parent_entry_id <> id", name="ck_session_entries_no_self_parent"),
        sa.ForeignKeyConstraint(
            ["first_kept_entry_id"], ["session_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"], ondelete="SET NULL"),
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
    op.create_index("ix_session_entries_tool_call_id", "session_entries", ["tool_call_id"])
    op.create_index("ix_session_entries_type", "session_entries", ["session_id", "entry_type"])
