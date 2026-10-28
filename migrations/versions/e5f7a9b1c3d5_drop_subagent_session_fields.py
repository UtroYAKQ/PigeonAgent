"""drop subagent-only session columns

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a0b2c4
Create Date: 2026-10-26 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d5"
down_revision: str | Sequence[str] | None = "d4e6f8a0b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_sessions_parent_session_id", table_name="sessions")
    op.drop_column("sessions", "parent_session_id")
    op.drop_column("sessions", "origin")


def downgrade() -> None:
    op.add_column("sessions", sa.Column("parent_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "origin", sa.String(length=16), nullable=False, server_default=sa.text("'root'")
        ),
    )
    op.create_foreign_key(
        "fk_sessions_parent_session_id_sessions",
        "sessions",
        "sessions",
        ["parent_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_sessions_parent_session_id", "sessions", ["parent_session_id"])
