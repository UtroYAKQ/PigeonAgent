"""blobs, files, file_upload_sessions tables

Revision ID: c9d2e5a7b4f6
Revises: b2e4d6f8a1c3
Create Date: 2026-10-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d2e5a7b4f6"
down_revision: Union[str, Sequence[str], None] = "b2e4d6f8a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blobs",
        sa.Column("hash_id", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("hash_id"),
    )
    op.create_index(op.f("ix_blobs_storage_key"), "blobs", ["storage_key"], unique=True)
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("blob_hash", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_files_owner_id"), "files", ["owner_id"])
    op.create_index(op.f("ix_files_blob_hash"), "files", ["blob_hash"])
    op.create_index(op.f("ix_files_deleted_at"), "files", ["deleted_at"])
    op.create_index(
        "ix_files_owner_id_deleted_at", "files", ["owner_id", "deleted_at"]
    )
    op.create_table(
        "file_upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("declared_sha256", sa.String(length=64), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_file_upload_sessions_owner_id"), "file_upload_sessions", ["owner_id"])


def downgrade() -> None:
    op.drop_index(
        op.f("ix_file_upload_sessions_owner_id"), table_name="file_upload_sessions"
    )
    op.drop_table("file_upload_sessions")
    op.drop_index("ix_files_owner_id_deleted_at", table_name="files")
    op.drop_index(op.f("ix_files_deleted_at"), table_name="files")
    op.drop_index(op.f("ix_files_blob_hash"), table_name="files")
    op.drop_index(op.f("ix_files_owner_id"), table_name="files")
    op.drop_table("files")
    op.drop_index(op.f("ix_blobs_storage_key"), table_name="blobs")
    op.drop_table("blobs")
