"""应用配置项表

Revision ID: d3e5a7c9b1f4
Revises: b1f7c2e9a4d6
Create Date: 2026-10-31 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e5a7c9b1f4"
down_revision: str | Sequence[str] | None = "b1f7c2e9a4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("is_secret", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_configs_key", "app_configs", ["key"], unique=True)
    op.create_index("ix_app_configs_category", "app_configs", ["category"])


def downgrade() -> None:
    op.drop_index("ix_app_configs_category", table_name="app_configs")
    op.drop_index("ix_app_configs_key", table_name="app_configs")
    op.drop_table("app_configs")
