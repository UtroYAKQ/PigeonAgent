"""add run_seq to session_entries

Revision ID: f8a2c1b3d5e6
Revises: a3b5c8d9e2f4
Create Date: 2026-10-25 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8a2c1b3d5e6"
down_revision: Union[str, Sequence[str], None] = "a3b5c8d9e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "session_entries",
        sa.Column("run_seq", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_session_entries_run",
        "session_entries",
        ["session_id", "run_seq", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_session_entries_run", table_name="session_entries")
    op.drop_column("session_entries", "run_seq")
