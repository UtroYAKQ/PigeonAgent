"""drop run kind

Revision ID: b7d1e3f5a9c2
Revises: a1c3e5f7b9d2
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1e3f5a9c2"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 一次可见轮次 = 一条 run；resume 续写同一条，kind 不再有第二种值。
    op.drop_column("chat_request_logs", "kind")
    op.drop_column("session_runs", "kind")


def downgrade() -> None:
    op.add_column(
        "chat_request_logs",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default=sa.text("'turn'")),
    )
    op.add_column(
        "session_runs",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default=sa.text("'turn'")),
    )
