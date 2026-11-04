"""add image model protocol

Revision ID: e2b4c6d8f0a1
Revises: d8f1c3b5a7e9
Create Date: 2026-11-01 17:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b4c6d8f0a1"
down_revision: str | Sequence[str] | None = "d8f1c3b5a7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_models",
        sa.Column(
            "protocol",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'openai'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("image_models", "protocol")
