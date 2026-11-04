"""模型展示图标

Revision ID: b1f7c2e9a4d6
Revises: c4d8f1a6b2e9
Create Date: 2026-10-30 20:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f7c2e9a4d6"
down_revision: str | Sequence[str] | None = "c4d8f1a6b2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column("icon", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "icon")
