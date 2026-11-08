"""admin managed MCP servers

Revision ID: d3e7a1c9f5b2
Revises: c4d8e2f6a1b3
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e7a1c9f5b2"
down_revision: str | Sequence[str] | None = "c4d8e2f6a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("auth_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("defer_loading", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("120"), nullable=False),
        sa.Column("tool_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mcp_servers_name", "mcp_servers", ["name"], unique=True)
    op.create_index("ix_mcp_servers_slug", "mcp_servers", ["slug"], unique=True)
    op.add_column(
        "sessions",
        sa.Column(
            "mcp_server_ids",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "mcp_server_ids")
    op.drop_index("ix_mcp_servers_slug", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_name", table_name="mcp_servers")
    op.drop_table("mcp_servers")
