"""run 树读写的不变量：路径分页、租约、分支一致性、状态。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.exceptions import (
    ModelConnectionError,
    ModelContextWindowExceededError,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.turn import _error_item
from app.core.exceptions import ConflictError
from app.enums import RunKind, RunStatus
from app.schemas.run_item import (
    CustomItem,
    ErrorItem,
    TextItem,
    ToolResultItem,
)
from app.services import item_codec
from app.services import session_run as run_service
from tests.helpers import (
    all_runs,
    append_run,
    append_user_run,
    approval_call,
    assistant,
    head,
    make_session,
    user,
)


async def test_pending_path_reads_full_runs(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    first = await append_user_run(db_session, session_id, "u0")
    second = await append_user_run(db_session, session_id, "u1")

    runs, more = await run_service.path_runs(db_session, session_id, limit=1)
    assert [run.id for run in runs] == [second.id]
    assert more is True

    older, more = await run_service.path_runs(
        db_session, session_id, limit=1, before_run_id=second.id
    )
    assert [run.id for run in older] == [first.id]
    assert more is False


async def test_parent_from_other_session_is_rejected(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    other = await make_session(db_session)
    foreign = await append_user_run(db_session, other, "别人的根")

    with pytest.raises(Exception, match="not found"):
        await run_service.create_run(
            db_session,
            session_id,
            run_id=uuid4(),
            content=[CustomItem(renderer="card")],
            parent_run_id=foreign.id,
        )
    assert len(await all_runs(db_session, session_id)) == 0


async def test_lease_renewal_only_touches_matching_run(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await run_service.reserve_lease(db_session, session_id, "run-1")
    stale = await head(db_session, session_id)
    assert stale.active_run_expires_at is not None
    stale.active_run_expires_at = datetime.now(UTC) - timedelta(seconds=100)
    await db_session.commit()

    await run_service.renew_run_lease(db_session, session_id, "run-1")
    renewed = await head(db_session, session_id)
    assert renewed.active_run_id == "run-1"
    expiry = renewed.active_run_expires_at
    assert expiry is not None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    assert expiry > datetime.now(UTC)

    await run_service.renew_run_lease(db_session, session_id, "run-other")
    assert (await head(db_session, session_id)).active_run_id == "run-1"


async def test_expired_lease_is_reclaimable(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await run_service.reserve_lease(db_session, session_id, "run-dead")
    chat_session = await head(db_session, session_id)
    chat_session.active_run_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert run_service.run_is_live(chat_session) is False
    await run_service.reserve_lease(db_session, session_id, "run-2")
    assert (await head(db_session, session_id)).active_run_id == "run-2"


async def test_live_lease_still_blocks_a_second_run(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await run_service.reserve_lease(db_session, session_id, "run-1")

    assert run_service.run_is_live(await head(db_session, session_id)) is True
    with pytest.raises(ConflictError, match="active run"):
        await run_service.reserve_lease(db_session, session_id, "run-2")


async def test_startup_sweep_only_reclaims_expired_leases(db_session: AsyncSession) -> None:
    dead = await make_session(db_session)
    alive = await make_session(db_session)
    await run_service.reserve_lease(db_session, dead, "run-dead")
    await run_service.reserve_lease(db_session, alive, "run-alive")
    stale = await head(db_session, dead)
    stale.active_run_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    await run_service.clear_active_runs(db_session)

    assert (await head(db_session, dead)).active_run_id is None
    assert (await head(db_session, alive)).active_run_id == "run-alive"


async def test_declare_interrupts_isolated_per_session(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    other = await make_session(db_session)
    foreign = await append_user_run(db_session, other, "别人的问题")
    requests = item_codec.to_request_items(
        DeferredToolRequests(approvals=[approval_call()], calls=[])
    )

    with pytest.raises(Exception, match="not found"):
        await run_service.append_items(db_session, session_id, foreign.id, requests)


async def test_path_ids_bounded_when_history_forms_a_cycle(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    first = await append_user_run(db_session, session_id, "u1")
    second = await append_user_run(db_session, session_id, "u2")
    first.parent_run_id = second.id
    await db_session.commit()

    ids = await run_service.path_ids(db_session, session_id, second.id)
    assert len(ids) <= 3


def test_custom_card_defaults_to_version_one_and_out_of_context() -> None:
    item = CustomItem(renderer="status-card", data={"title": "t"})
    assert item.version == 1
    assert item.in_context is False


def test_error_item_classifies_by_exception_type() -> None:
    connection = ModelConnectionError("gpt-4o-mini", "Connection reset")
    assert _error_item(connection).retryable is True
    assert _error_item(connection).code == "ModelConnectionError"
    assert isinstance(_error_item(connection), ErrorItem)

    window = ModelContextWindowExceededError("gpt-4o-mini", "too long")
    overflow = _error_item(window)
    assert overflow.retryable is False
    assert overflow.code == "context_window_exceeded"

    limit = UsageLimitExceeded("budget exhausted")
    assert _error_item(limit).code == "usage_limit_exceeded"
    assert _error_item(limit).retryable is False

    unknown = _error_item(RuntimeError("炸了"))
    assert (unknown.code, unknown.retryable, unknown.message) == ("RuntimeError", False, "炸了")


def test_tool_failure_is_not_an_error_item() -> None:
    """工具失败只是普通 ToolResultItem，不进 ErrorItem。"""
    items = item_codec.items_from_message(
        ModelRequest(parts=[ToolReturnPart("read", "boom", "c1", outcome="failed")])
    )
    results = [item for item in items if isinstance(item, ToolResultItem)]
    assert len(results) == 1
    assert results[0].outcome == "failed"
    assert not any(isinstance(item, ErrorItem) for item in items)


async def test_run_preview_and_status(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    run = await append_run(db_session, session_id, [user("预览文本"), assistant("回答")])
    await run_service.set_run_status(db_session, session_id, run.id, RunStatus.FAILED)

    runs, _ = await run_service.path_runs(db_session, session_id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "预览文本" in runs[0].preview


async def test_branch_navs_follow_the_latest_tip(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    root = await append_user_run(db_session, session_id, "A")
    resumed = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[TextItem(role="user", text="A2")],
        parent_run_id=root.id,
        kind=RunKind.RESUME,
    )
    sibling = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[TextItem(role="user", text="B")],
        parent_run_id=None,
    )

    navs = await run_service.branch_navs(db_session, session_id, [root, sibling])

    assert navs[root.id].position == 1
    assert navs[root.id].total == 2
    assert navs[root.id].leaves == [resumed.id, sibling.id]
    assert navs[sibling.id].position == 2
    assert navs[sibling.id].leaves == [resumed.id, sibling.id]


async def test_retry_copies_user_items_and_creates_sibling(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    root = await append_user_run(db_session, session_id, "问题")
    original = await run_service.start_run_turn(
        db_session, session_id, run_id=str(uuid4()), user_input="问题"
    )
    # original 不该是 root 的孩子：start_run_turn 默认接在当前叶子（root）下面
    assert original.parent_run_id == root.id
    active_id = (await head(db_session, session_id)).active_run_id
    assert active_id is not None
    await run_service.finish_run(db_session, session_id, active_id)

    retry = await run_service.start_run_turn(
        db_session, session_id, run_id=str(uuid4()), retry_run_id=original.id
    )
    assert retry.parent_run_id == root.id
    assert any(isinstance(item, TextItem) and item.text == "问题" for item in retry.content)
    assert retry.id != original.id
