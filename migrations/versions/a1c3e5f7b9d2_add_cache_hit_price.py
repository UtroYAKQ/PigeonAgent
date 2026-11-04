"""add cache hit price to llm models

Revision ID: a1c3e5f7b9d2
Revises: 72b03e4edf1b
Create Date: 2026-11-02 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | Sequence[str] | None = "72b03e4edf1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("credit_cache_read_per_1m", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "credit_cache_read_per_1m")
