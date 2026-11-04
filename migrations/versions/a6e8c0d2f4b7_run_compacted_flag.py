"""run compacted flag

Revision ID: a6e8c0d2f4b7
Revises: f5b2d8c4a1e7
Create Date: 2026-10-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6e8c0d2f4b7"
down_revision: str | Sequence[str] | None = "f5b2d8c4a1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_runs",
        sa.Column("compacted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("session_runs", "compacted")
