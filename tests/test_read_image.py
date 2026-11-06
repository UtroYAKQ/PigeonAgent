"""读图工具：引用/路径两种来源、媒体剥离与回放。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from pydantic_ai import ToolReturn
from pydantic_ai.messages import (
    BinaryContent,
    FunctionToolResultEvent,
    ToolReturnPart,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import codec
from app.agents.tools.image import make_read_image
from app.agents.turn import AgentTurn, _reported_tool_outcome
from app.core.config import Settings
from app.domain.run_items import (
    MEDIA_FILE_ID_KEY,
    ImageItem,
    ToolCallItem,
    ToolResultItem,
)
from app.models.file_record import FileRecord
from app.sandbox.workspace import LocalWorkspace
from app.services import file_service
from app.services import run_store as run_service
from tests.helpers import append_user_run, head, make_session
from tests.test_files import FakeStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def _settings(tmp_path: Path | None = None) -> Settings:
    if tmp_path is None:
        return Settings(secret_key="x" * 44)
    return Settings(secret_key="x" * 44, workspace_root=str(tmp_path))


async def _seed(
    db: AsyncSession,
    storage: FakeStorage,
    *,
    owner: uuid.UUID | None = None,
    data: bytes = PNG,
    name: str = "pic.png",
    mime: str = "image/png",
) -> Any:
    return await file_service.direct_upload(db, _settings(), storage, owner, name, mime, data)


async def test_read_image_by_storage_key_returns_reference_and_bytes(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    storage = FakeStorage()
    record = await _seed(db_session, storage)
    tool = make_read_image(
        db_session_factory,
        owner_id=None,
        settings=_settings(),
        storage=storage,
        workspace=None,
    )

    result = await tool(str(record.id))

    assert isinstance(result, ToolReturn)
    reference, image = result.return_value
    assert reference["storage_key"] == str(record.id)
    assert reference["name"] == "pic.png"
    assert reference["media_type"] == "image/png"
    assert reference["size"] == len(PNG)
    assert isinstance(image, BinaryContent)
    assert image.data == PNG and image.media_type == "image/png"
    assert result.metadata[MEDIA_FILE_ID_KEY] == str(record.id)


async def test_read_image_rejects_non_image_and_foreign_file(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    storage = FakeStorage()
    doc = await _seed(db_session, storage, data=b"%PDF-1.7", name="a.pdf", mime="application/pdf")
    foreign = await _seed(db_session, storage, owner=uuid.uuid4(), name="theirs.png")
    tool = make_read_image(
        db_session_factory,
        owner_id=None,
        settings=_settings(),
        storage=storage,
        workspace=None,
    )

    pdf_result = await tool(str(doc.id))
    assert "只读 PNG/JPEG/WebP/GIF" in pdf_result.return_value["error"]

    foreign_result = await tool(str(foreign.id))
    assert "不存在" in foreign_result.return_value["error"]

    missing_result = await tool(str(uuid.uuid4()))
    assert "不存在" in missing_result.return_value["error"]


async def test_read_image_path_uploads_once_and_returns_reference(
    tmp_path: Path, db_session: AsyncSession, db_session_factory: Any
) -> None:
    storage = FakeStorage()
    settings = _settings(tmp_path)
    workspace = LocalWorkspace(settings, storage, uuid.uuid4(), "run-1")
    (workspace.root / "out").mkdir(parents=True, exist_ok=True)
    (workspace.root / "out" / "chart.png").write_bytes(PNG)

    owner = uuid.uuid4()
    tool = make_read_image(
        db_session_factory,
        owner_id=owner,
        settings=settings,
        storage=storage,
        workspace=workspace,
    )

    result = await tool("out/chart.png")

    reference, image = result.return_value
    assert reference["name"] == "chart.png"
    assert reference["media_type"] == "image/png"
    assert isinstance(image, BinaryContent)

    async with db_session_factory() as db:
        record = await db.get(FileRecord, uuid.UUID(reference["storage_key"]))
        assert record is not None
        assert record.owner_id == owner and record.name == "chart.png"


async def test_read_image_path_rejects_non_image_and_traversal(
    tmp_path: Path, db_session: AsyncSession, db_session_factory: Any
) -> None:
    storage = FakeStorage()
    settings = _settings(tmp_path)
    workspace = LocalWorkspace(settings, storage, uuid.uuid4(), "run-1")
    (workspace.root / "note.txt").write_text("not an image", encoding="utf-8")
    tool = make_read_image(
        db_session_factory,
        owner_id=None,
        settings=settings,
        storage=storage,
        workspace=workspace,
    )

    text_result = await tool("note.txt")
    assert "只读 PNG/JPEG/WebP/GIF" in text_result.return_value["error"]

    traversal = await tool("../secret.png")
    error = traversal.return_value["error"]
    assert "非法路径" in error or "不在工作区" in error


def test_stripped_tool_media_round_trips_by_metadata() -> None:
    file_id = str(uuid.uuid4())
    part = ToolReturnPart(
        tool_name="read_image",
        tool_call_id="call_1",
        content=[
            {"storage_key": file_id, "name": "pic.png", "media_type": "image/png"},
            BinaryContent(data=PNG, media_type="image/png"),
        ],
        metadata={MEDIA_FILE_ID_KEY: file_id, "name": "pic.png", "media_type": "image/png"},
    )

    item = codec.tool_result_item(part)
    item.content = codec.without_binary_media(item.content)
    assert item.content == [{"storage_key": file_id, "name": "pic.png", "media_type": "image/png"}]

    without_media = codec.messages_from_items([item])[0].parts[0]
    assert isinstance(without_media, ToolReturnPart)
    assert without_media.content == item.content

    rebuilt = codec.messages_from_items([item], media={file_id: (PNG, "image/png")})[0].parts[0]
    assert isinstance(rebuilt, ToolReturnPart)
    assert isinstance(rebuilt.content, list)
    assert isinstance(rebuilt.content[-1], BinaryContent)
    assert rebuilt.content[-1].data == PNG


async def test_turn_persists_reference_without_base64() -> None:
    file_id = str(uuid.uuid4())
    event = FunctionToolResultEvent(
        part=ToolReturnPart(
            tool_name="read_image",
            tool_call_id="call_1",
            content=[
                {"storage_key": file_id, "name": "pic.png", "media_type": "image/png"},
                BinaryContent(data=PNG, media_type="image/png"),
            ],
            metadata={MEDIA_FILE_ID_KEY: file_id},
        )
    )
    store = _RecordingStore()
    turn = AgentTurn(object(), store, None)  # type: ignore[arg-type]

    await turn._on_tool_result(event)

    [item] = store.appended
    assert isinstance(item, ToolResultItem)
    assert item.content == [{"storage_key": file_id, "name": "pic.png", "media_type": "image/png"}]
    assert item.metadata == {MEDIA_FILE_ID_KEY: file_id}

    reported = _reported_tool_outcome(event)
    assert isinstance(reported.part.content, list)
    assert not any(isinstance(part, BinaryContent) for part in reported.part.content)


async def test_unreferenced_binary_is_kept_in_history() -> None:
    """没有 file_id 可回填的二进制不能剥，否则历史里就永久丢了。"""
    event = FunctionToolResultEvent(
        part=ToolReturnPart(
            tool_name="legacy_shot",
            tool_call_id="call_1",
            content=["截图", BinaryContent(data=PNG, media_type="image/png")],
        )
    )
    store = _RecordingStore()
    turn = AgentTurn(object(), store, None)  # type: ignore[arg-type]

    await turn._on_tool_result(event)

    [item] = store.appended
    assert item.content[1]["media"] == "binary"
    assert item.content[1]["media_type"] == "image/png"

    reported = _reported_tool_outcome(event)
    assert isinstance(reported.part.content[-1], BinaryContent)


async def test_build_context_skips_display_only_media(
    db_session: AsyncSession, monkeypatch: Any
) -> None:
    """in_context=False 的生成图不该每轮从对象存储下载。"""
    session_id = await make_session(db_session)
    visible_id = str(uuid.uuid4())
    hidden_id = str(uuid.uuid4())
    await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid.uuid4(),
        content=[
            ImageItem(role="user", file_id=visible_id, media_type="image/png"),
            ImageItem(
                role="assistant",
                file_id=hidden_id,
                media_type="image/png",
                in_context=False,
            ),
        ],
    )
    captured: list[str] = []

    async def fake_load(db: Any, ids: Any, *, storage: Any = None) -> dict[str, Any]:
        captured.extend(ids)
        return {}

    monkeypatch.setattr(file_service, "load_media", fake_load)
    await run_service.build_context(db_session, session_id)

    assert captured == [visible_id]


async def test_build_context_rehydrates_tool_result_media(
    db_session: AsyncSession, monkeypatch: Any, tmp_path: Path
) -> None:
    storage = FakeStorage()
    record = await _seed(db_session, storage)
    session_id = await make_session(db_session)
    await append_user_run(db_session, session_id, "看看这张图")
    chat_session = await head(db_session, session_id)
    await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid.uuid4(),
        content=[
            ToolCallItem(tool_call_id="call_1", tool_name="read_image", args={"source": "x"}),
            ToolResultItem(
                tool_call_id="call_1",
                tool_name="read_image",
                content=[{"storage_key": str(record.id), "name": "pic.png"}],
                metadata={MEDIA_FILE_ID_KEY: str(record.id)},
            ),
        ],
        parent_run_id=chat_session.active_leaf_run_id,
    )
    monkeypatch.setattr(file_service, "get_storage", lambda: storage)

    context = await run_service.build_context(db_session, session_id)

    parts = [
        part
        for message in context.messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert parts and isinstance(parts[0].content, list)
    assert isinstance(parts[0].content[-1], BinaryContent)
    assert parts[0].content[-1].data == PNG


class _RecordingStore:
    def __init__(self) -> None:
        self.appended: list[Any] = []

    async def append_items(self, items: list[Any], *, usage: Any = None) -> list[Any]:
        self.appended.extend(items)
        return list(items)

    async def flush(self) -> None:
        return None
