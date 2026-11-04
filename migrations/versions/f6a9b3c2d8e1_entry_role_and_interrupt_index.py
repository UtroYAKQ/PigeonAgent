"""role as a denormalized column for the tree skeleton + interrupt lookup index

Revision ID: f6a9b3c2d8e1
Revises: b3c7d1e9f4a2
Create Date: 2026-10-26 00:00:00.000000

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "f6a9b3c2d8e1"
down_revision: str | Sequence[str] | None = "b3c7d1e9f4a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session_entries",
        sa.Column("role", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_session_entries_interrupt",
        "session_entries",
        ["session_id", "interrupt_id"],
    )
    _backfill_roles(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_session_entries_interrupt", table_name="session_entries")
    op.drop_column("session_entries", "role")


def _backfill_roles(bind: Any) -> None:
    """存量 message entry 从 payload 推 role；与应用内 message_role() 同一套规则。"""
    rows = bind.execute(
        sa.text("SELECT id, payload FROM session_entries WHERE type = 'message'")
    ).all()
    for entry_id, payload in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        role = _message_role(payload.get("message") if isinstance(payload, dict) else None)
        if role is None:
            continue
        bind.execute(
            sa.text("UPDATE session_entries SET role = :role WHERE id = :id"),
            {"role": role, "id": entry_id},
        )


def _message_role(message: dict[str, Any] | None) -> str | None:
    if not isinstance(message, dict):
        return None
    if message.get("kind") == "response":
        return "assistant"
    kinds = {
        part.get("part_kind")
        for part in message.get("parts", [])
        if isinstance(part, dict) and part.get("part_kind")
    }
    if "system-prompt" in kinds:
        return "system"
    if "tool-return" in kinds:
        return "tool_result"
    return "user"
