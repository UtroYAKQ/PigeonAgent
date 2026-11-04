"""session group names unique per owner

Revision ID: c6a9d3e1f8b2
Revises: a6e8c0d2f4b7
Create Date: 2026-10-31 12:00:00.000000

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "c6a9d3e1f8b2"
down_revision: str | Sequence[str] | None = "a6e8c0d2f4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_session_groups_owner_id_name"
NAME_MAX = 60

session_groups = sa.table(
    "session_groups",
    sa.column("id", sa.Integer()),
    sa.column("owner_id", sa.Uuid()),
    sa.column("name", sa.String(length=NAME_MAX)),
)


def _available_name(connection: Connection, owner_id: UUID, name: str, start: int) -> str:
    number = start
    while True:
        suffix = f" ({number})"
        candidate = f"{name[: NAME_MAX - len(suffix)]}{suffix}"
        taken = connection.scalar(
            sa.select(sa.func.count())
            .select_from(session_groups)
            .where(
                session_groups.c.owner_id == owner_id,
                session_groups.c.name == candidate,
            )
        )
        if not taken:
            return candidate
        number += 1


def _dedupe(connection: Connection) -> None:
    """建唯一索引前给历史重名分组加序号，避免迁移直接失败。"""
    duplicates = connection.execute(
        sa.select(session_groups.c.owner_id, session_groups.c.name)
        .where(session_groups.c.owner_id.is_not(None))
        .group_by(session_groups.c.owner_id, session_groups.c.name)
        .having(sa.func.count() > 1)
    ).all()
    for owner_id, name in duplicates:
        ids = connection.scalars(
            sa.select(session_groups.c.id)
            .where(
                session_groups.c.owner_id == owner_id,
                session_groups.c.name == name,
            )
            .order_by(session_groups.c.id)
        ).all()
        for number, group_id in enumerate(ids[1:], start=2):
            connection.execute(
                session_groups.update()
                .where(session_groups.c.id == group_id)
                .values(name=_available_name(connection, owner_id, name, number))
            )


def upgrade() -> None:
    _dedupe(op.get_bind())
    op.create_index(INDEX_NAME, "session_groups", ["owner_id", "name"], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="session_groups")
