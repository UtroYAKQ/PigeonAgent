"""开轮互斥、批次幂等、分支独立：run 树靠行锁和路径判断守住不变量。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnprocessableError
from app.schemas.run_item import ToolResultItem
from app.services import session_run as run_service
from tests.helpers import (
    append_user_run,
    approval_call,
    declare_pending,
    head,
    make_session,
    path,
    pending,
    price_call,
)


async def pending_call_ids(db_session: AsyncSession, session_id: UUID) -> list[str]:
    return [
        item.tool_call_id
        for batch in await pending(db_session, session_id)
        for item in batch.interrupts
    ]


async def test_active_run_conflicts_when_session_busy(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    assert await path(db_session, session_id) == []

    await run_service.reserve_lease(db_session, session_id, "run-1")

    with pytest.raises(ConflictError):
        await run_service.reserve_lease(db_session, session_id, "run-2")
    # 冲突必须回滚，不能把 SELECT ... FOR UPDATE 的行锁留着
    assert db_session.in_transaction() is False


async def test_pending_blocks_only_its_own_branch(db_session: AsyncSession) -> None:
    """分支 A 挂着中断不该锁死会话：切到分支 B 照样能开新轮。"""
    session_id = await make_session(db_session)
    question = await append_user_run(db_session, session_id, "删掉 a.txt")
    question_id = question.id
    declaring, _ = await declare_pending(db_session, session_id, [approval_call()])
    declaring_id = declaring.id

    with pytest.raises(ConflictError, match="pending interrupts"):
        await run_service.start_run_turn(
            db_session, session_id, run_id=str(uuid4()), user_input="新问题"
        )

    # 从同一个问题处分叉：新分支上没有那条未决的 tool call
    sibling = await append_user_run(db_session, session_id, "换个方向", parent_run_id=question_id)
    await run_service.switch_leaf(db_session, session_id, sibling.id)
    await run_service.start_run_turn(
        db_session, session_id, run_id=str(uuid4()), user_input="在新分支上问"
    )

    assert (await head(db_session, session_id)).active_run_id is not None
    # pending 只看当前分支；结束当前 run 后切回声明批次的分支才看得到
    assert await pending_call_ids(db_session, session_id) == []
    active_id = (await head(db_session, session_id)).active_run_id
    assert active_id is not None
    await run_service.finish_run(db_session, session_id, active_id)
    await run_service.switch_leaf(db_session, session_id, declaring_id)
    assert await pending_call_ids(db_session, session_id) == ["call_1"]


async def test_resume_rejects_unknown_call(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    run, interrupts = await declare_pending(db_session, session_id, [approval_call()])
    run_id = run.id
    batch_id = interrupts[0].interrupt_id

    with pytest.raises(UnprocessableError, match="is not pending"):
        await run_service.start_run_turn(
            db_session,
            session_id,
            run_id=str(uuid4()),
            resume=run_service.ResumeDecisions(
                interrupt_id=batch_id, approvals={"call-missing": True}
            ),
        )
    assert db_session.in_transaction() is False
    reloaded = await run_service.get_run_or_404(db_session, session_id, run_id)
    assert any(getattr(item, "interrupt_id", None) == batch_id for item in reloaded.content)


async def test_resume_requires_a_pending_batch(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await declare_pending(db_session, session_id, [approval_call()])

    with pytest.raises(ConflictError, match="not pending"):
        await run_service.start_run_turn(
            db_session,
            session_id,
            run_id=str(uuid4()),
            resume=run_service.ResumeDecisions(
                interrupt_id=UUID(int=0), approvals={"call_1": True}
            ),
        )
    assert db_session.in_transaction() is False


async def test_resume_must_cover_every_interrupt_in_the_batch(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    _, interrupts = await declare_pending(db_session, session_id, [approval_call(), price_call()])

    with pytest.raises(UnprocessableError, match="must cover"):
        await run_service.start_run_turn(
            db_session,
            session_id,
            run_id=str(uuid4()),
            resume=run_service.ResumeDecisions(
                interrupt_id=interrupts[0].interrupt_id, approvals={"call_1": True}
            ),
        )
    assert db_session.in_transaction() is False


async def test_resume_claims_the_branch_and_resolves_after_the_run(
    db_session: AsyncSession,
) -> None:
    """开轮只把叶子挪到那条分支；决定等 run 跑完才落。"""
    session_id = await make_session(db_session)
    declaring, interrupts = await declare_pending(db_session, session_id, [approval_call()])
    declaring_id = declaring.id
    batch_id = interrupts[0].interrupt_id
    sibling = await append_user_run(
        db_session, session_id, "另一条分支", parent_run_id=declaring_id
    )
    sibling_id = sibling.id
    await run_service.switch_leaf(db_session, session_id, sibling.id)

    resumed = await run_service.start_run_turn(
        db_session,
        session_id,
        run_id=str(uuid4()),
        resume=run_service.ResumeDecisions(interrupt_id=batch_id, approvals={"call_1": True}),
    )

    # 这一步还没写决定：批次仍未决，run 崩了可以原地重试
    runs = await path(db_session, session_id)
    assert [run.id for run in runs] == [declaring_id, resumed.id]
    assert (await head(db_session, session_id)).active_leaf_run_id == resumed.id
    assert [batch.interrupt_id for batch in await pending(db_session, session_id)] == [batch_id]

    # 模拟 resume run 里工具结果 + 审批回复事件已落库
    resumed_id = resumed.id
    await run_service.append_items(
        db_session,
        session_id,
        resumed_id,
        [ToolResultItem(tool_call_id="call_1", tool_name="delete_file", content="deleted")],
    )
    db_session.expire_all()

    reloaded = await run_service.get_run_or_404(db_session, session_id, resumed_id)
    assert any(isinstance(item, ToolResultItem) for item in reloaded.content)
    assert await pending(db_session, session_id) == []
    # 上一轮的分支还留在库里，只是不在当前路径上
    assert sibling_id not in {run.id for run in await path(db_session, session_id)}


async def test_expired_lease_is_reclaimable(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await run_service.reserve_lease(db_session, session_id, "run-dead")
    chat_session = await head(db_session, session_id)
    chat_session.active_run_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert run_service.run_is_live(chat_session) is False
    await run_service.reserve_lease(db_session, session_id, "run-2")
    assert (await head(db_session, session_id)).active_run_id == "run-2"


async def test_startup_sweep_only_reclaims_expired_leases(db_session: AsyncSession) -> None:
    dead = await make_session(db_session, "dead")
    alive = await make_session(db_session, "alive")
    await run_service.reserve_lease(db_session, dead, "run-dead")
    await run_service.reserve_lease(db_session, alive, "run-alive")
    stale = await head(db_session, dead)
    stale.active_run_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    await run_service.clear_active_runs(db_session)

    assert (await head(db_session, dead)).active_run_id is None
    assert (await head(db_session, alive)).active_run_id == "run-alive"


async def test_resend_from_pending_turn_parent_is_allowed(
    db_session: AsyncSession,
) -> None:
    """改提问/重新生成从更早节点开新分支，不该被当前叶子的 pending 拦住。"""
    session_id = await make_session(db_session)
    root = await append_user_run(db_session, session_id, "原始问题")
    declaring, _ = await declare_pending(db_session, session_id, [approval_call()])
    root_id, declaring_id = root.id, declaring.id

    edited = await run_service.start_run_turn(
        db_session,
        session_id,
        run_id=str(uuid4()),
        user_input="改后的问题",
        parent_run_id=root_id,
        parent_was_given=True,
    )

    assert edited.parent_run_id == root_id
    assert await pending(db_session, session_id) == []
    active_id = (await head(db_session, session_id)).active_run_id
    assert active_id is not None
    await run_service.finish_run(db_session, session_id, active_id)
    await run_service.switch_leaf(db_session, session_id, declaring_id)
    assert [
        item.tool_call_id
        for batch in await pending(db_session, session_id)
        for item in batch.interrupts
    ] == ["call_1"]
