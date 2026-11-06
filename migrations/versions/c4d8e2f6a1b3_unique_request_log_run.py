"""unique request log run

Revision ID: c4d8e2f6a1b3
Revises: b7d1e3f5a9c2
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4d8e2f6a1b3"
down_revision: str | Sequence[str] | None = "b7d1e3f5a9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 一个 run 只留一条日志：先清掉历史上可能存在的重复，保留最新的一条
    op.execute(
        """
        DELETE FROM chat_request_logs AS older
        USING chat_request_logs AS newer
        WHERE older.run_id IS NOT NULL
          AND older.run_id = newer.run_id
          AND (coalesce(older.created_at, 'epoch'::timestamptz), older.id)
              < (coalesce(newer.created_at, 'epoch'::timestamptz), newer.id)
        """
    )
    op.drop_index("ix_chat_request_logs_run_id", table_name="chat_request_logs")
    op.create_index(
        "ix_chat_request_logs_run_id", "chat_request_logs", ["run_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_chat_request_logs_run_id", table_name="chat_request_logs")
    op.create_index("ix_chat_request_logs_run_id", "chat_request_logs", ["run_id"])
