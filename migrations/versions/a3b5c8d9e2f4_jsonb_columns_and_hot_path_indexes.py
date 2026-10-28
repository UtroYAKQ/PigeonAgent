"""JSONB columns and hot-path indexes

Revision ID: a3b5c8d9e2f4
Revises: c79baf7d27cd
Create Date: 2026-10-24 10:30:12.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a3b5c8d9e2f4"
down_revision: Union[str, Sequence[str], None] = "c79baf7d27cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSONB_COLUMNS = ("content", "payload", "usage")


def upgrade() -> None:
    op.create_index("ix_sessions_last_entry_at", "sessions", ["last_entry_at"], unique=False)
    op.create_index(
        "ix_session_entries_status",
        "session_entries",
        ["status", "updated_at"],
        unique=False,
    )
    # SQLite 迁移沿用 JSON 类型，跳过 JSONB 转换
    if op.get_bind().dialect.name == "postgresql":
        for column in _JSONB_COLUMNS:
            op.execute(
                f"ALTER TABLE session_entries ALTER COLUMN {column} "
                f"TYPE JSONB USING {column}::jsonb"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for column in _JSONB_COLUMNS:
            op.execute(
                f"ALTER TABLE session_entries ALTER COLUMN {column} TYPE JSON USING {column}::json"
            )
    op.drop_index("ix_session_entries_status", table_name="session_entries")
    op.drop_index("ix_sessions_last_entry_at", table_name="sessions")
