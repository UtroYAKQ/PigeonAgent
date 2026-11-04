"""unified operation logs

Revision ID: e6a7b8c9d0f1
Revises: d2f4a6b8c0e1
Create Date: 2026-10-31 17:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6a7b8c9d0f1"
down_revision: str | Sequence[str] | None = "d2f4a6b8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "operation_logs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'request'"),
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=254), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("query", _JSON, nullable=True),
        sa.Column("request_body", _JSON, nullable=True),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", _JSON, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("request_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("response_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("request_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("response_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", _JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_logs_created_at", "operation_logs", ["created_at"])
    op.create_index(
        "ix_operation_logs_actor_created", "operation_logs", ["actor_id", "created_at"]
    )
    op.create_index(
        "ix_operation_logs_route_created", "operation_logs", ["route", "created_at"]
    )
    op.create_index(
        "ix_operation_logs_status_created", "operation_logs", ["status_code", "created_at"]
    )
    op.create_index("ix_operation_logs_request_id", "operation_logs", ["request_id"])
    op.create_index("ix_operation_logs_action", "operation_logs", ["action"])

    # 旧管理员审计迁移成统一日志的 admin 事件
    op.execute(
        sa.text(
            """
            INSERT INTO operation_logs
                (kind, actor_id, actor_email, action, target_type, target_id, detail, created_at)
            SELECT 'admin', actor_id, actor_email, action, target_type, target_id, detail, created_at
            FROM audit_logs
            """
        )
    )
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")


def downgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=254), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.execute(
        sa.text(
            """
            INSERT INTO audit_logs
                (actor_id, actor_email, action, target_type, target_id, detail, created_at)
            SELECT actor_id, actor_email, action, target_type, target_id, detail, created_at
            FROM operation_logs WHERE kind = 'admin'
            """
        )
    )
    op.drop_table("operation_logs")
