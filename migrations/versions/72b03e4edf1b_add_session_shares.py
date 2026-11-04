"""会话只读分享链接表

Revision ID: 72b03e4edf1b
Revises: 25833ef4db9d
Create Date: 2026-11-02 07:05:56.869288

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "72b03e4edf1b"
down_revision: str | Sequence[str] | None = "25833ef4db9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        # sha256(口令) hex：公开读取按它精确匹配，库里不留可用链接
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        # SECRET_KEY 加密的口令原文，只为了让主人能再次复制链接
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("visit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_visited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_session_shares_expires_at"), "session_shares", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_session_shares_session_id"), "session_shares", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_session_shares_token_hash"), "session_shares", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_session_shares_token_hash"), table_name="session_shares")
    op.drop_index(op.f("ix_session_shares_session_id"), table_name="session_shares")
    op.drop_index(op.f("ix_session_shares_expires_at"), table_name="session_shares")
    op.drop_table("session_shares")
