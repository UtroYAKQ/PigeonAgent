"""add per-model compaction threshold

Revision ID: c7e5b1a9d3f2
Revises: b4d6f8a0c2e4
Create Date: 2026-11-01 13:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e5b1a9d3f2"
down_revision: str | Sequence[str] | None = "b4d6f8a0c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_models", sa.Column("compaction_threshold", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_llm_models_compaction_threshold_range",
        "llm_models",
        "compaction_threshold IS NULL OR "
        "(compaction_threshold >= 0.1 AND compaction_threshold <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_llm_models_compaction_threshold_range", "llm_models", type_="check"
    )
    op.drop_column("llm_models", "compaction_threshold")
