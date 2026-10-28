"""files and upload sessions allow anonymous owner

Revision ID: 146c02746d3d
Revises: c9d2e5a7b4f6
Create Date: 2026-10-28 23:17:09.389442

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "146c02746d3d"
down_revision: Union[str, Sequence[str], None] = "c9d2e5a7b4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """匿名上传路径：owner_id 允许为空。"""
    op.alter_column("files", "owner_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column(
        "file_upload_sessions", "owner_id", existing_type=sa.UUID(), nullable=True
    )


def downgrade() -> None:
    op.alter_column("file_upload_sessions", "owner_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("files", "owner_id", existing_type=sa.UUID(), nullable=False)
