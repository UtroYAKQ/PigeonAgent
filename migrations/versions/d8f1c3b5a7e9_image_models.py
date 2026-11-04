"""add image models

Revision ID: d8f1c3b5a7e9
Revises: c7e5b1a9d3f2
Create Date: 2026-11-01 14:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8f1c3b5a7e9"
down_revision: str | Sequence[str] | None = "c7e5b1a9d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "image_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("sizes", _JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "default_size",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'1024x1024'"),
        ),
        sa.Column("max_images", sa.Integer(), nullable=False, server_default=sa.text("4")),
        sa.Column("quality", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.CheckConstraint(
            "max_images > 0 AND max_images <= 8", name="ck_image_models_max_images"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_image_models_name", "image_models", ["name"], unique=True)
    op.create_index(
        "uq_image_models_single_default",
        "image_models",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_image_models_single_default", table_name="image_models")
    op.drop_index("ix_image_models_name", table_name="image_models")
    op.drop_table("image_models")
