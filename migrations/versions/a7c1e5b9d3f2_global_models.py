"""llm_models 全局共享，仅管理员可配置

模型不再归属单个用户：去掉 owner_id 与按用户唯一的默认项索引，
默认模型改回全局唯一。写入权限由端点层的管理员依赖控制。

Revision ID: a7c1e5b9d3f2
Revises: b8e4c6d2f0a7
Create Date: 2026-10-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1e5b9d3f2"
down_revision: str | Sequence[str] | None = "b8e4c6d2f0a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT_INDEX = "uq_llm_models_owner_single_default"
NEW_DEFAULT_INDEX = "uq_llm_models_single_default"


def upgrade() -> None:
    # 每个用户各有一个默认项，共享后只能留一条：保留 id 最小的那条
    op.execute(
        sa.text(
            "UPDATE llm_models SET is_default = FALSE "
            "WHERE is_default = TRUE "
            "AND id <> (SELECT MIN(id) FROM llm_models WHERE is_default = TRUE)"
        )
    )

    op.drop_index(OLD_DEFAULT_INDEX, table_name="llm_models")
    op.drop_index("ix_llm_models_owner_id", table_name="llm_models")
    op.drop_column("llm_models", "owner_id")
    op.create_index(
        NEW_DEFAULT_INDEX,
        "llm_models",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(NEW_DEFAULT_INDEX, table_name="llm_models")
    op.add_column("llm_models", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_llm_models_owner_id", "llm_models", ["owner_id"])
    op.create_index(
        OLD_DEFAULT_INDEX,
        "llm_models",
        ["owner_id", "is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )
