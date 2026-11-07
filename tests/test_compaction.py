"""上下文压缩：标记落库、上下文从标记处重建、turn 自动压缩与事件。"""

from typing import Any, ClassVar
from uuid import uuid4

import pytest
from ag_ui.core import CustomEvent as AguiCustomEvent
from pydantic_ai.messages import SystemPromptPart, UserPromptPart
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import codec
from app.agents.base import BaseAgent
from app.domain.run_items import CompactionItem, TextItem
from app.schemas.run import SessionRunRead
from app.services import run as run_service
from app.services.run import context as run_context
from tests.helpers import (
    append_run,
    append_user_run,
    assistant,
    make_session,
    path,
    texts_of,
    user,
)


class CompactAgent(BaseAgent):
    name: ClassVar[str] = "compact-demo"
    instructions: ClassVar[str] = "你是测试助手。"


def make_agent(
    db_session: AsyncSession,
    session_id: Any,
    *,
    context_window: int = 4,
    output: str = "好的",
) -> CompactAgent:
    return CompactAgent(
        TestModel(custom_output_text=output, call_tools=[]),
        db=db_session,
        session_id=session_id,
        context_window=context_window,
        compaction_threshold=0.5,
    )


async def test_context_starts_at_compaction_item(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    parent = await append_user_run(db_session, session_id, "很久以前的问题")
    run = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[
            TextItem(role="user", text="压缩点之前的内容"),
            CompactionItem(summary="早先的结论"),
            TextItem(role="user", text="压缩点之后的内容"),
        ],
        parent_run_id=parent.id,
    )
    run.compacted = True
    await db_session.commit()

    context = await run_service.build_context(db_session, session_id)

    assert [item.id for item in context.runs] == [run.id]
    texts = texts_of(context.messages)
    assert any("早先的结论" in text for text in texts)
    assert "压缩点之后的内容" in texts
    assert "压缩点之前的内容" not in texts
    assert "很久以前的问题" not in texts


async def test_context_loads_only_from_last_compaction(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """压缩点之前的 run 连 content 都不该反序列化，长会话的每轮成本才能降下来。"""
    session_id = await make_session(db_session)
    older = await append_user_run(db_session, session_id, "压缩点之前的问题")
    marker = await append_user_run(db_session, session_id, "压缩点所在轮")
    await run_service.record_compaction(
        db_session, session_id, marker.id, CompactionItem(summary="早期结论")
    )
    tail_a = await append_user_run(db_session, session_id, "之后的第一问")
    tail_b = await append_user_run(db_session, session_id, "之后的第二问")

    captured: list[Any] = []
    original = run_context.load_by_ids

    async def spy(db: AsyncSession, ids: Any) -> Any:
        captured.extend(ids)
        return await original(db, ids)

    monkeypatch.setattr(run_context, "load_by_ids", spy)

    context = await run_service.build_context(db_session, session_id)

    assert captured == [marker.id, tail_a.id, tail_b.id]
    assert [run.id for run in context.runs] == [marker.id, tail_a.id, tail_b.id]
    assert older.id not in captured
    assert "压缩点之前的问题" not in texts_of(context.messages)


async def test_context_uses_nearest_compaction_marker(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    first = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[
            CompactionItem(summary="第一份摘要"),
            TextItem(role="user", text="第一份摘要之后"),
        ],
    )
    first.compacted = True
    second = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[
            CompactionItem(summary="第二份摘要"),
            TextItem(role="user", text="第二份摘要之后"),
        ],
        parent_run_id=first.id,
    )
    second.compacted = True
    await db_session.commit()

    context = await run_service.build_context(db_session, session_id)

    assert [run.id for run in context.runs] == [second.id]
    texts = texts_of(context.messages)
    assert any("第二份摘要" in text for text in texts)
    assert "第二份摘要之后" in texts
    assert all("第一份摘要" not in text for text in texts)
    assert "第一份摘要之后" not in texts


async def test_record_compaction_prepends_item_and_marks_run(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    run = await append_user_run(db_session, session_id, "本轮问题")
    item = CompactionItem(summary="摘要", tokens_before=1200, items_compacted=6)

    updated = await run_service.record_compaction(db_session, session_id, run.id, item)

    assert updated.compacted is True
    assert isinstance(updated.content[0], CompactionItem)
    assert updated.content[0].summary == "摘要"
    assert isinstance(updated.content[1], TextItem)
    assert updated.content[1].text == "本轮问题"
    assert SessionRunRead.model_validate(updated).compacted is True


def test_compaction_item_becomes_system_summary() -> None:
    messages = codec.messages_from_items(
        [
            CompactionItem(summary="保留的要点 A"),
            TextItem(role="user", text="继续"),
        ]
    )

    assert isinstance(messages[0].parts[0], SystemPromptPart)
    assert "保留的要点 A" in messages[0].parts[0].content
    assert isinstance(messages[0].parts[1], UserPromptPart)
    assert messages[0].parts[1].content == "继续"


async def test_turn_compacts_before_second_request(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)

    await agent.run("第一轮")
    await agent.run("第二轮")

    runs = await path(db_session, session_id)
    assert len(runs) == 2
    second = runs[1]
    assert second.compacted is True
    assert isinstance(second.content[0], CompactionItem)
    assert second.content[0].summary == "好的"
    assert isinstance(second.content[1], TextItem)
    assert second.content[1].text == "第二轮"
    assert second.usage.requests >= 2

    context = await run_service.build_context(db_session, session_id)
    texts = texts_of(context.messages)
    assert any("好的" in text for text in texts)
    assert "第二轮" in texts
    assert all("第一轮" not in text for text in texts)


async def test_compaction_events_are_forwarded_to_agui(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)
    await agent.run("第一轮")

    events = [event async for event in agent.agui_events("第二轮")]

    custom = [event for event in events if isinstance(event, AguiCustomEvent)]
    names = [event.name for event in custom]
    assert names[:2] == ["compaction_start", "compaction_result"]
    start = custom[0].value
    assert start["estimated_tokens"] > 0
    result = custom[1].value
    assert result["summary"] == "好的"
    assert result["tokens_before"] > 0

    runs = await path(db_session, session_id)
    assert len([item for item in runs[-1].content if isinstance(item, CompactionItem)]) == 1


async def test_compaction_skipped_when_context_fits(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id, context_window=1_000_000)

    await agent.run("第一轮")
    await agent.run("第二轮")

    runs = await path(db_session, session_id)
    assert all(not run.compacted for run in runs)
    assert all(not isinstance(item, CompactionItem) for run in runs for item in run.content)


async def test_compaction_uses_prior_summary_as_history(db_session: AsyncSession) -> None:
    """再次压缩时，输入是「上一份摘要 + 之后的消息」，而不是最原始的整段历史。"""
    session_id = await make_session(db_session)
    await append_run(db_session, session_id, [user("很久前的原文"), assistant("很久前的回答")])
    old = await append_user_run(db_session, session_id, "上一轮问题")
    await run_service.record_compaction(
        db_session,
        session_id,
        old.id,
        CompactionItem(summary="上一份摘要", tokens_before=900),
    )

    agent = make_agent(db_session, session_id)
    await agent.run("这一轮")

    latest = (await path(db_session, session_id))[-1]
    assert latest.compacted is True
    context = await run_service.build_context(db_session, session_id)
    texts = texts_of(context.messages)
    assert any("这一轮" in text for text in texts)
    assert all("很久前的原文" not in text for text in texts)
