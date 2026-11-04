"""users.token_version + sessions.pending_batches

Revision ID: d2f4a6b8c0e1
Revises: a9c4e2f6b8d1
Create Date: 2026-10-31 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4a6b8c0e1"
down_revision: str | Sequence[str] | None = "a9c4e2f6b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.execute(sa.text("UPDATE users SET email_verified = is_active"))
    op.add_column(
        "sessions",
        sa.Column("pending_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("sessions", "pending_batches")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "token_version")
