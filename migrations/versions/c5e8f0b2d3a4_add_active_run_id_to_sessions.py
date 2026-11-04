"""add active_run_id to sessions

Revision ID: c5e8f0b2d3a4
Revises: b4d7e9a1c2f3
Create Date: 2026-10-25 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e8f0b2d3a4"
down_revision: Union[str, Sequence[str], None] = "b4d7e9a1c2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("active_run_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "active_run_id")
