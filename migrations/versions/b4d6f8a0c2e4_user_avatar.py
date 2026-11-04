"""add user avatar

Revision ID: b4d6f8a0c2e4
Revises: e6a7b8c9d0f1
Create Date: 2026-11-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d6f8a0c2e4"
down_revision: str | Sequence[str] | None = "e6a7b8c9d0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_file_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_file_id")
