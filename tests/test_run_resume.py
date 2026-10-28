"""HTTP 审批/外部调用恢复：中断挂在 run 的 ToolCallItem 上，resume 另开一个 run。"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from uuid import UUID

from httpx import AsyncClient
from pydantic_ai import Tool
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.llm_model import LlmModel
from app.schemas.session import SessionCreate
from app.services import chat_session as session_service
from app.services import run as run_service
from app.services.model_factory import ModelFactory, ResolvedModel
from tests.conftest import TEST_USER_ID

DANGEROUS_TOOL = "delete_file"


class ApprovalAgent(BaseAgent):
    name: ClassVar[str] = "approval-http"

    def default_tools(self) -> list[Tool[Any]]:
        def delete_file(path: str) -> str:
            return f"deleted {path}"

        return [Tool(delete_file, name=DANGEROUS_TOOL, requires_approval=True)]


class ExternalCallAgent(BaseAgent):
    name: ClassVar[str] = "external-http"

    def default_tools(self) -> list[Tool[Any]]:
        def fetch_price(symbol: str) -> str:
            raise CallDeferred(metadata={"source": "vendor"})

        return [Tool(fetch_price, name="fetch_price")]


class TwoApprovalsAgent(BaseAgent):
    name: ClassVar[str] = "two-approvals"

    def default_tools(self) -> list[Tool[Any]]:
        def delete_file(path: str) -> str:
            return f"deleted {path}"

        def drop_table(table: str) -> str:
            return f"dropped {table}"

        return [
            Tool(delete_file, name="delete_file", requires_approval=True),
            Tool(drop_table, name="drop_table", requires_approval=True),
        ]


class TwoCallsAgent(BaseAgent):
    name: ClassVar[str] = "two-calls"

    def default_tools(self) -> list[Tool[Any]]:
        def fetch_a(symbol: str) -> str:
            raise CallDeferred()

        def fetch_b(symbol: str) -> str:
            raise CallDeferred()

        return [Tool(fetch_a, name="fetch_a"), Tool(fetch_b, name="fetch_b")]


class MixedAgent(BaseAgent):
    name: ClassVar[str] = "mixed-http"

    def default_tools(self) -> list[Tool[Any]]:
        def delete_file(path: str) -> str:
            return f"deleted {path}"

        def fetch_price(symbol: str) -> str:
            raise CallDeferred()

        return [
            Tool(delete_file, name=DANGEROUS_TOOL, requires_approval=True),
            Tool(fetch_price, name="fetch_price"),
        ]


async def wait_until(condition: Callable[[], Awaitable[bool]], limit: float = 5.0) -> None:
    deadline = time.monotonic() + limit
    while not await condition():
        if time.monotonic() > deadline:
            raise AssertionError("运行超时未结束")
        await asyncio.sleep(0.02)


async def wait_run_finished(client: AsyncClient, session_id: UUID) -> None:
    async def done() -> bool:
        response = await client.get(f"/api/v1/sessions/{session_id}")
        return response.json()["active_run_id"] is None

    await wait_until(done)


async def list_runs(client: AsyncClient, session_id: UUID) -> list[dict[str, Any]]:
    listing = await client.get(f"/api/v1/sessions/{session_id}/runs")
    items: list[dict[str, Any]] = listing.json()["items"]
    return items


async def get_run(client: AsyncClient, session_id: UUID, run_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/sessions/{session_id}/runs/{run_id}")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def pending_batches(client: AsyncClient, session_id: UUID) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/sessions/{session_id}/pending")
    items: list[dict[str, Any]] = response.json()
    return items


async def pending_items(client: AsyncClient, session_id: UUID) -> list[dict[str, Any]]:
    return [
        item for batch in await pending_batches(client, session_id) for item in batch["interrupts"]
    ]


def items_of_type(run: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [item for item in run["content"] if item["type"] == kind]


def tool_call_ids(run: dict[str, Any]) -> set[str]:
    return {item["tool_call_id"] for item in items_of_type(run, "tool_call")}


async def seed_session(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: Any,
    agent_cls: type[BaseAgent] = ApprovalAgent,
    *,
    call_tools: bool = True,
) -> UUID:
    model = LlmModel(
        name="approval-model",
        provider="openai",
        model_name="gpt-4o-mini",
        owner_id=TEST_USER_ID,
        supports_tools=True,
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    created = await session_service.create_session(
        db_session,
        SessionCreate(title="审批", model_id=model.id),
        owner_id=TEST_USER_ID,
    )

    resolved = ResolvedModel(
        name="approval-model",
        model=TestModel() if call_tools else TestModel(call_tools=[]),
        settings={},
        context_window=None,
        supports_tools=True,
    )
    monkeypatch.setattr(ModelFactory, "create", lambda _self, _record: resolved)
    monkeypatch.setattr(run_service, "BaseAgent", agent_cls)
    return created.id


async def interrupt_of(client: AsyncClient, session_id: UUID, kind: str) -> dict[str, Any]:
    """跑一轮直到挂出某种中断，返回它所在的批次。"""
    started = await client.post(f"/api/v1/sessions/{session_id}/runs", json={"input": "干活"})
    assert started.status_code == 202
    await wait_run_finished(client, session_id)

    batch = next(
        (
            item
            for item in await pending_batches(client, session_id)
            if any(i["kind"] == kind for i in item["interrupts"])
        ),
        None,
    )
    assert batch is not None

    declared = await get_run(client, session_id, batch["run_id"])
    assert {item["tool_call_id"] for item in batch["interrupts"]} == tool_call_ids(declared)
    return batch


async def test_interrupt_only_records_descriptor(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, ExternalCallAgent)
    batch = await interrupt_of(client, session_id, "call")

    # 中断描述符只留 id / tool_call_id / kind，工具参数仍在 ToolCallItem 里
    assert set(batch["interrupts"][0]) == {"interrupt_id", "tool_call_id", "kind"}
    assert batch["interrupts"][0]["interrupt_id"] == batch["interrupt_id"]
    runs = await list_runs(client, session_id)
    assert all(not items_of_type(run, "tool_result") for run in runs)
    requests = items_of_type(runs[0], "call_request")
    assert len(requests) == 1
    assert requests[0]["tool_call_ids"] == [batch["interrupts"][0]["tool_call_id"]]


async def test_resume_approves_and_executes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch)
    batch = await interrupt_of(client, session_id, "approval")
    interrupt_id = batch["interrupt_id"]
    call_id = batch["interrupts"][0]["tool_call_id"]

    resumed = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={"interrupt_id": interrupt_id, "approvals": {call_id: True}},
    )
    assert resumed.status_code == 202
    await wait_run_finished(client, session_id)

    assert await pending_items(client, session_id) == []
    runs = await list_runs(client, session_id)
    assert len(runs) == 2
    resume_run = runs[-1]
    assert resume_run["parent_run_id"] == batch["run_id"]
    results = items_of_type(resume_run, "tool_result")
    assert any(item["tool_call_id"] == call_id for item in results)
    assert items_of_type(resume_run, "text")


async def test_resume_denies_without_running_tool(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch)
    batch = await interrupt_of(client, session_id, "approval")

    resumed = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={
            "interrupt_id": batch["interrupt_id"],
            "approvals": {batch["interrupts"][0]["tool_call_id"]: False},
        },
    )
    assert resumed.status_code == 202
    await wait_run_finished(client, session_id)

    runs = await list_runs(client, session_id)
    results = items_of_type(runs[-1], "tool_result")
    assert results
    assert [item["outcome"] for item in results] == ["denied"]
    assert all("deleted" not in str(item["content"]) for item in results)


async def test_resume_must_cover_every_interrupt(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, MixedAgent)
    batch = await interrupt_of(client, session_id, "approval")
    approval_id = next(
        item["tool_call_id"] for item in batch["interrupts"] if item["kind"] == "approval"
    )

    runs = await list_runs(client, session_id)
    requests = items_of_type(runs[0], "approval_request") + items_of_type(runs[0], "call_request")
    assert len(requests) == 2
    assert {item["interrupt_id"] for item in requests} == {batch["interrupt_id"]}

    partial = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={"interrupt_id": batch["interrupt_id"], "approvals": {approval_id: True}},
    )
    assert partial.status_code == 422
    assert "must cover" in partial.json()["detail"]

    runs = await list_runs(client, session_id)
    assert all(not items_of_type(run, "tool_result") for run in runs)
    response = await client.get(f"/api/v1/sessions/{session_id}")
    assert response.json()["active_run_id"] is None


async def test_resume_rejects_unknown_call(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch)
    batch = await interrupt_of(client, session_id, "approval")

    resumed = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={"interrupt_id": batch["interrupt_id"], "approvals": {"call-missing": True}},
    )
    assert resumed.status_code == 422
    runs = await list_runs(client, session_id)
    assert all(not items_of_type(run, "tool_result") for run in runs)


async def test_new_run_is_blocked_until_interrupts_resolve(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch)
    await interrupt_of(client, session_id, "approval")

    again = await client.post(f"/api/v1/sessions/{session_id}/runs", json={"input": "新问题"})
    assert again.status_code == 409
    assert await pending_items(client, session_id)


async def test_resume_twice_conflicts(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch)
    batch = await interrupt_of(client, session_id, "approval")
    body = {
        "interrupt_id": batch["interrupt_id"],
        "approvals": {batch["interrupts"][0]["tool_call_id"]: True},
    }

    first = await client.post(f"/api/v1/sessions/{session_id}/runs/resume", json=body)
    assert first.status_code == 202
    await wait_run_finished(client, session_id)

    second = await client.post(f"/api/v1/sessions/{session_id}/runs/resume", json=body)
    assert second.status_code == 409
    runs = await list_runs(client, session_id)
    assert sum(len(items_of_type(run, "approval_request")) for run in runs) == 1


async def test_same_batch_approvals_share_one_item(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, TwoApprovalsAgent)
    batch = await interrupt_of(client, session_id, "approval")
    items = batch["interrupts"]
    assert len(items) == 2, "两个审批都挂上了"
    assert len({item["interrupt_id"] for item in items}) == 1, "同批共享一个批次 id"

    resumed = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={
            "interrupt_id": batch["interrupt_id"],
            "approvals": {item["tool_call_id"]: True for item in items},
        },
    )
    assert resumed.status_code == 202
    await wait_run_finished(client, session_id)

    runs = await list_runs(client, session_id)
    requests = items_of_type(runs[0], "approval_request")
    assert len(requests) == 1, "同批审批请求必须汇在一个 ApprovalRequestItem 里"
    assert set(requests[0]["tool_call_ids"]) == {item["tool_call_id"] for item in items}
    results = items_of_type(runs[-1], "tool_result")
    assert len(results) == 2
    assert {item["tool_call_id"] for item in results} == {item["tool_call_id"] for item in items}


async def test_batch_calls_share_request_and_tool_results(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, TwoCallsAgent)
    batch = await interrupt_of(client, session_id, "call")
    items = batch["interrupts"]
    assert len(items) == 2
    assert len({item["interrupt_id"] for item in items}) == 1

    runs = await list_runs(client, session_id)
    requests = items_of_type(runs[0], "call_request")
    assert len(requests) == 1
    assert set(requests[0]["tool_call_ids"]) == {item["tool_call_id"] for item in items}

    resumed = await client.post(
        f"/api/v1/sessions/{session_id}/runs/resume",
        json={
            "interrupt_id": batch["interrupt_id"],
            "calls": {item["tool_call_id"]: f"result-{item['tool_call_id']}" for item in items},
        },
    )
    assert resumed.status_code == 202
    await wait_run_finished(client, session_id)

    assert await pending_items(client, session_id) == []
    runs = await list_runs(client, session_id)
    results = items_of_type(runs[-1], "tool_result")
    assert len(results) == 2
    assert {item["tool_call_id"] for item in results} == {item["tool_call_id"] for item in items}

