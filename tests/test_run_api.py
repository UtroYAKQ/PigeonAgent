"""run API：分支信息、重新生成、改提问、分页和手工卡片。"""

from typing import Any, ClassVar
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.enums import RunStatus
from app.services import session_run as run_service_data
from tests.helpers import make_session
from tests.test_run_resume import seed_session, wait_run_finished


class PlainAgent(BaseAgent):
    name: ClassVar[str] = "plain-http"


async def start_run(
    client: AsyncClient, session_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(f"/api/v1/sessions/{session_id}/runs", json=payload)
    assert response.status_code == 202, response.text
    await wait_run_finished(client, session_id)
    body: dict[str, Any] = response.json()
    return body


async def runs_of(client: AsyncClient, session_id: UUID) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/sessions/{session_id}/runs")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_run_branch_info_and_regenerate(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(client, session_id, {"input": "干活"})
    first = await runs_of(client, session_id)
    assert len(first) == 1
    assert first[0]["parent_run_id"] is None
    assert first[0]["branch"] is None
    assert [item["type"] for item in first[0]["content"]] == ["text", "text"]

    retried = await start_run(client, session_id, {"retry_run_id": first[0]["id"]})
    assert retried["run_id"]
    current = await runs_of(client, session_id)
    assert [run["id"] for run in current] == [retried["run_id"]]
    assert current[0]["parent_run_id"] is None
    assert current[0]["content"][0]["text"] == "干活"
    assert current[0]["branch"] == {
        "position": 2,
        "total": 2,
        "leaves": [first[0]["id"], retried["run_id"]],
    }

    # 切回旧分支，上下文跟着切
    switched = await client.post(
        f"/api/v1/sessions/{session_id}/leaf", json={"leaf_run_id": first[0]["id"]}
    )
    assert switched.status_code == 200
    current = await runs_of(client, session_id)
    assert [run["id"] for run in current] == [first[0]["id"]]
    assert current[0]["branch"] == {
        "position": 1,
        "total": 2,
        "leaves": [first[0]["id"], retried["run_id"]],
    }
    context = await client.get(f"/api/v1/sessions/{session_id}/context")
    assert "干活" in str(context.json()["messages"])


async def test_edit_first_question_creates_root_sibling(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(client, session_id, {"input": "原始问题"})
    original = (await runs_of(client, session_id))[0]

    await start_run(client, session_id, {"input": "改后的问题", "parent_run_id": None})

    current = await runs_of(client, session_id)
    assert len(current) == 1
    assert current[0]["content"][0]["text"] == "改后的问题"
    assert current[0]["branch"] == {
        "position": 2,
        "total": 2,
        "leaves": [original["id"], current[0]["id"]],
    }


async def test_run_with_attachments(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    """图片走 attachments（file_id），文档走 resources（storage_key 标签）。"""
    from tests.test_files import FakeStorage, storage_override

    storage_override(FakeStorage())
    image = await client.post(
        "/api/v1/files", files={"file": ("a.png", b"\x89PNG\r\n\x1a\nplaceholder", "image/png")}
    )
    assert image.status_code == 201, image.text
    image_id = image.json()["id"]
    doc = await client.post(
        "/api/v1/files", files={"file": ("notes.md", b"# notes", "text/markdown")}
    )
    assert doc.status_code == 201, doc.text
    doc_id = doc.json()["id"]

    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(
        client,
        session_id,
        {
            "input": "看看这些附件",
            "attachments": [
                {
                    "kind": "image",
                    "name": "a.png",
                    "media_type": "image/png",
                    "file_id": image_id,
                }
            ],
            "resources": [{"storage_key": doc_id, "name": "notes.md"}],
        },
    )

    runs = await runs_of(client, session_id)
    assert len(runs) == 1
    content = runs[0]["content"]
    assert [item["type"] for item in content if item.get("role") == "user"] == [
        "text",
        "image",
        "resource",
    ]
    image_item = next(item for item in content if item["type"] == "image")
    assert image_item["file_id"] == image_id
    resource = next(item for item in content if item["type"] == "resource")
    assert (resource["storage_key"], resource["name"]) == (doc_id, "notes.md")

    context = await client.get(f"/api/v1/sessions/{session_id}/context")
    assert f'storage_key="{doc_id}"' in str(context.json()["messages"])


async def test_run_with_uploaded_image_attachment(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    """走 /files 上传的图片只传 file_id，落库时名字和 mime 以入库记录为准。"""
    from tests.test_files import FakeStorage, storage_override

    storage_override(FakeStorage())
    uploaded = await client.post(
        "/api/v1/files",
        files={"file": ("pic.png", b"\x89PNG\r\n\x1a\nreal", "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]

    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(
        client,
        session_id,
        {
            "input": "看图",
            "attachments": [
                {
                    "kind": "image",
                    "name": "自报名字.png",
                    "media_type": "image/png",
                    "file_id": file_id,
                }
            ],
        },
    )

    runs = await runs_of(client, session_id)
    image = next(item for item in runs[0]["content"] if item["type"] == "image")
    assert image["file_id"] == file_id
    assert image["alt"] == "pic.png"
    assert image["data"] is None and image["url"] is None


async def test_run_rejects_missing_attachment_file_id(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    response = await client.post(
        f"/api/v1/sessions/{session_id}/runs",
        json={
            "input": "看图",
            "attachments": [
                {
                    "kind": "image",
                    "name": "ghost.png",
                    "media_type": "image/png",
                    "file_id": str(uuid4()),
                }
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert "不存在或已被删除" in response.text


async def test_run_can_be_attachment_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    from tests.test_files import FakeStorage, storage_override

    fake = FakeStorage()
    storage_override(fake)
    # 上下文重建走的是模块级 get_storage()，不在 FastAPI 依赖里
    monkeypatch.setattr("app.services.file_service.get_storage", lambda: fake)
    uploaded = await client.post(
        "/api/v1/files", files={"file": ("only.png", b"\x89PNG\r\n\x1a\nonly-image", "image/png")}
    )
    assert uploaded.status_code == 201, uploaded.text

    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(
        client,
        session_id,
        {
            "attachments": [
                {
                    "kind": "image",
                    "name": "only.png",
                    "media_type": "image/png",
                    "file_id": uploaded.json()["id"],
                }
            ]
        },
    )

    runs = await runs_of(client, session_id)
    assert runs[0]["status"] == "completed"
    assert runs[0]["content"][0]["type"] == "image"


async def test_runs_page_along_the_path(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    for text in ("一", "二", "三"):
        await start_run(client, session_id, {"input": text})

    page = await client.get(f"/api/v1/sessions/{session_id}/runs", params={"limit": 2})
    body = page.json()
    assert [run["content"][0]["text"] for run in body["items"]] == ["二", "三"]
    assert body["has_more"] is True

    older = await client.get(
        f"/api/v1/sessions/{session_id}/runs",
        params={"limit": 2, "before_run_id": body["items"][0]["id"]},
    )
    assert [run["content"][0]["text"] for run in older.json()["items"]] == ["一"]
    assert older.json()["has_more"] is False


async def test_custom_item_only_out_of_context(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    session_id = await seed_session(client, db_session, monkeypatch, PlainAgent, call_tools=False)
    await start_run(client, session_id, {"input": "干活"})
    run = (await runs_of(client, session_id))[0]

    response = await client.post(
        f"/api/v1/sessions/{session_id}/runs/{run['id']}/items",
        json={"type": "custom", "renderer": "status-card", "data": {"title": "卡片"}},
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    custom = next(item for item in content if item["type"] == "custom")
    assert custom["renderer"] == "status-card"
    assert custom["in_context"] is False

    context = await client.get(f"/api/v1/sessions/{session_id}/context")
    assert "卡片" not in str(context.json()["messages"])


async def test_custom_item_conflicts_with_live_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    session_id = await make_session(db_session)
    run = await run_service_data.create_run(
        db_session,
        session_id,
        run_id=UUID(int=1),
        content=[],
        status=RunStatus.COMPLETED,
    )
    await run_service_data.reserve_lease(db_session, session_id, "run-live")

    response = await client.post(
        f"/api/v1/sessions/{session_id}/runs/{run.id}/items",
        json={"type": "custom", "renderer": "status-card"},
    )
    assert response.status_code == 409


async def test_run_rejects_bad_frontend_tool_declarations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """前端工具必须带命名空间的 name，parameters 必须是 object schema。"""
    session_id = await make_session(db_session)
    bad_tools = [
        {"name": "preview", "description": "缺命名空间", "parameters": {}},
        {
            "name": "ui_preview",
            "description": "参数不是 object schema",
            "parameters": {"type": "string"},
        },
    ]
    for tool in bad_tools:
        response = await client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"input": "试一下", "tools": [tool]},
        )
        assert response.status_code == 422, tool["name"]
