from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RunStatus
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services import run_store as run_store
from tests.helpers import append_user_run


async def create_session(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/sessions", json={"title": "会话", **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_and_get_session(client: AsyncClient) -> None:
    created = await create_session(client)

    assert created["status"] == "active"
    assert created["run_seq"] == 0
    assert created["format_version"] == 5
    assert created["active_run_id"] is None
    assert created["active_leaf_run_id"] is None
    assert "pending_interrupts" not in created

    response = await client.get(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_list_sessions_paginates_and_filters(client: AsyncClient) -> None:
    for index in range(3):
        await create_session(client, title=f"s{index}")

    response = await client.get("/api/v1/sessions", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    await client.patch(f"/api/v1/sessions/{page['items'][0]['id']}", json={"status": "archived"})
    response = await client.get("/api/v1/sessions", params={"status": "archived"})
    assert response.json()["total"] == 1


async def test_search_sessions_by_title_and_message_preview(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    apple = await create_session(client, title="苹果发布")
    await create_session(client, title="香蕉计划")
    conversation = await create_session(client, title="普通标题")
    await append_user_run(db_session, UUID(conversation["id"]), "请分析奇异果的销量")

    by_title = await client.get("/api/v1/sessions", params={"q": "苹果"})
    assert by_title.status_code == 200
    assert [item["id"] for item in by_title.json()["items"]] == [apple["id"]]

    by_preview = await client.get("/api/v1/sessions", params={"q": "奇异果"})
    assert by_preview.status_code == 200
    assert [item["id"] for item in by_preview.json()["items"]] == [conversation["id"]]

    escaped = await client.get("/api/v1/sessions", params={"q": "%"})
    assert escaped.status_code == 200
    assert escaped.json()["total"] == 0


async def test_update_session(client: AsyncClient) -> None:
    created = await create_session(client)

    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"title": "新标题", "status": "archived"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "新标题"
    assert response.json()["status"] == "archived"

    response = await client.patch(f"/api/v1/sessions/{created['id']}", json={"status": None})
    assert response.status_code == 422


async def test_create_session_rejects_unknown_model(client: AsyncClient) -> None:
    response = await client.post("/api/v1/sessions", json={"model_id": 999})
    assert response.status_code == 422
    assert response.json() == {"detail": "Model 999 not found"}


async def _thinking_model(
    db_session: AsyncSession, *, name: str = "thinking-model", levels: list[str] | None = None
) -> LlmModel:
    model = LlmModel(
        name=name,
        provider="openai",
        model_name="mock",
        thinking_levels=levels if levels is not None else ["low", "medium", "high"],
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


async def test_session_thinking_level_is_validated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    model = await _thinking_model(db_session)
    created = await create_session(client, model_id=model.id, thinking_level="low")
    assert created["thinking_level"] == "low"

    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"thinking_level": "high"}
    )
    assert response.status_code == 200
    assert response.json()["thinking_level"] == "high"

    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"thinking_level": "max"}
    )
    assert response.status_code == 422

    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"thinking_level": None}
    )
    assert response.status_code == 200
    assert response.json()["thinking_level"] is None

    response = await client.post(
        "/api/v1/sessions", json={"model_id": model.id, "thinking_level": "max"}
    )
    assert response.status_code == 422


async def test_session_without_model_uses_default_for_thinking_level(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    model = await _thinking_model(db_session, name="fallback-default", levels=["low", "high"])
    model.is_default = True
    await db_session.commit()

    created = await create_session(client)
    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"thinking_level": "high"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["thinking_level"] == "high"


async def test_switching_to_model_without_level_clears_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _thinking_model(db_session, name="with-levels")
    second = await _thinking_model(db_session, name="without-levels", levels=[])

    created = await create_session(client, model_id=first.id, thinking_level="medium")
    response = await client.patch(f"/api/v1/sessions/{created['id']}", json={"model_id": second.id})
    assert response.status_code == 200
    assert response.json()["thinking_level"] is None


async def test_mark_session_read_and_run_completion_sets_unread(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await create_session(client)
    session_id = UUID(created["id"])
    assert created["has_unread"] is False

    run = await run_store.create_run(
        db_session, session_id, run_id=uuid4(), status=RunStatus.RUNNING
    )
    await run_store.set_run_status(db_session, session_id, run.id, RunStatus.COMPLETED)

    session_row = await db_session.get(ChatSession, session_id)
    assert session_row is not None
    assert session_row.has_unread is True

    response = await client.post(f"/api/v1/sessions/{created['id']}/read")
    assert response.status_code == 200
    assert response.json()["has_unread"] is False
    assert response.json()["pending_batches"] == 0


async def test_get_missing_session_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_delete_session_cascades_runs_and_workspace(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from uuid import UUID

    from app.core.config import Settings
    from app.sandbox.workspace import local_workspace_root

    created = await create_session(client)
    session_id = UUID(created["id"])
    run = await append_user_run(db_session, session_id, "会被级联删除")
    workspace = local_workspace_root(Settings(_env_file=None), session_id)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "leftover.txt").write_text("x", encoding="utf-8")

    response = await client.delete(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 404

    remaining = await db_session.scalars(select(SessionRun).where(SessionRun.id == run.id))
    assert list(remaining) == []
    assert not workspace.exists()
