"""add session groups

Revision ID: 10cda6e42020
Revises: f7c2a9d4b1e8
Create Date: 2026-10-28 02:28:51.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10cda6e42020"
down_revision: str | Sequence[str] | None = "f7c2a9d4b1e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUP_FK = "fk_sessions_group_id"


def upgrade() -> None:
    op.create_table(
        "session_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("sessions", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_index("ix_sessions_group_id", "sessions", ["group_id"])
    # 删组时组内会话回到未分组，不连带删会话
    op.create_foreign_key(
        GROUP_FK, "sessions", "session_groups", ["group_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(GROUP_FK, "sessions", type_="foreignkey")
    op.drop_index("ix_sessions_group_id", table_name="sessions")
    op.drop_column("sessions", "group_id")
    op.drop_table("session_groups")
