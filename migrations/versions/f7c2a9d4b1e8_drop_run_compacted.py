"""drop run compacted flag

Revision ID: f7c2a9d4b1e8
Revises: e5f7a9b1c3d5
Create Date: 2026-10-27 05:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2a9d4b1e8"
down_revision: str | Sequence[str] | None = "e5f7a9b1c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_session_runs_compacted", table_name="session_runs")
    op.drop_column("session_runs", "compacted")


def downgrade() -> None:
    op.add_column(
        "session_runs",
        sa.Column(
            "compacted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_index(
        "ix_session_runs_compacted", "session_runs", ["session_id", "compacted", "seq"]
    )
