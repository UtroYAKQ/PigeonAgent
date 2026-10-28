"""sessions/groups/llm_models 归属用户

owner_id 直接挂 users.id，NULL 只可能是迁移前的遗留数据：
端点一律按当前用户过滤，孤儿行不再可见。

Revision ID: b8e4c6d2f0a7
Revises: 146c02746d3d
Create Date: 2026-10-29 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4c6d2f0a7"
down_revision: str | Sequence[str] | None = "146c02746d3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT_INDEX = "uq_llm_models_single_default"
NEW_DEFAULT_INDEX = "uq_llm_models_owner_single_default"


def upgrade() -> None:
    op.add_column("sessions", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_sessions_owner_id", "sessions", ["owner_id"])
    op.add_column("session_groups", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_session_groups_owner_id", "session_groups", ["owner_id"])

    # 默认模型从全局唯一改为按用户唯一
    op.drop_index(OLD_DEFAULT_INDEX, table_name="llm_models")
    op.add_column("llm_models", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_llm_models_owner_id", "llm_models", ["owner_id"])
    op.create_index(
        NEW_DEFAULT_INDEX,
        "llm_models",
        ["owner_id", "is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(NEW_DEFAULT_INDEX, table_name="llm_models")
    op.drop_index("ix_llm_models_owner_id", table_name="llm_models")
    op.drop_column("llm_models", "owner_id")
    op.create_index(
        OLD_DEFAULT_INDEX,
        "llm_models",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )
    op.drop_index("ix_session_groups_owner_id", table_name="session_groups")
    op.drop_column("session_groups", "owner_id")
    op.drop_index("ix_sessions_owner_id", table_name="sessions")
    op.drop_column("sessions", "owner_id")
