"""会话未读状态与模型思考挡位

Revision ID: c4d8f1a6b2e9
Revises: a7c1e5b9d3f2
Create Date: 2026-10-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d8f1a6b2e9"
down_revision: str | Sequence[str] | None = "a7c1e5b9d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "has_unread",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("thinking_level", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "llm_models",
        sa.Column(
            "thinking_levels",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "thinking_levels")
    op.drop_column("sessions", "thinking_level")
    op.drop_column("sessions", "has_unread")
