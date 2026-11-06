from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.agents.events import ImageGeneratedEvent
from app.agents.tools import image as image_tool
from app.agents.turn import AgentTurn
from app.domain.run_items import ImageItem, RunItem


class _RecordingStore:
    def __init__(self) -> None:
        self.appended: list[RunItem] = []
        self.flushes = 0

    async def append_items(self, items: list[RunItem], *, usage: Any = None) -> list[RunItem]:
        self.appended.extend(items)
        return list(items)

    async def flush(self) -> None:
        self.flushes += 1


async def test_turn_persists_image_event() -> None:
    file_id = str(uuid4())
    store = _RecordingStore()
    turn = AgentTurn(object(), store, None)  # type: ignore[arg-type]

    await turn._handle_record_event(
        ImageGeneratedEvent(
            file_id=file_id,
            file_name="generated-1.png",
            media_type="image/png",
            size=128,
            alt="雪山日出",
        )
    )

    assert len(store.appended) == 1
    image = store.appended[0]
    assert isinstance(image, ImageItem)
    assert image.role == "assistant"
    assert image.file_id == file_id
    assert image.name == "generated-1.png"
    assert image.media_type == "image/png"
    assert image.alt == "雪山日出"
    assert image.in_context is False
    assert store.flushes == 1
    # 事件本身会由 AG-UI 适配器转发给前端，turn 不再另造产物事件
    assert turn._drain_outbox() == []


@asynccontextmanager
async def _empty_session() -> AsyncIterator[object]:
    yield object()


class _RecordingContext:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> Any:
        self.events.append(event)
        return event


async def test_generate_image_tool_returns_keys_and_emits_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        name="Seedream",
        max_images=4,
        sizes=["1024x1024"],
        default_size="1024x1024",
    )
    charged: list[tuple[Any, int, Any]] = []

    async def fake_active_model(db: Any, model_id: int | None) -> Any:
        return record

    class FakeClient:
        async def generate(self, *, prompt: str, size: str, count: int) -> list[Any]:
            return [
                SimpleNamespace(data=b"png-bytes", media_type="image/png") for _ in range(count)
            ]

    async def fake_upload(
        db: Any,
        settings: Any,
        storage: Any,
        owner: Any,
        name: str,
        content_type: str,
        data: bytes,
    ) -> Any:
        return SimpleNamespace(id=uuid4(), name=name, size=len(data), content_type=content_type)

    async def fake_charge(
        db: Any,
        settings: Any,
        *,
        user_id: Any,
        model: Any,
        count: int,
        run_id: Any = None,
    ) -> float:
        charged.append((user_id, count, run_id))
        return 0

    monkeypatch.setattr(image_tool.image_model_service, "get_active_model", fake_active_model)
    monkeypatch.setattr(image_tool, "create_client", lambda record, settings: FakeClient())
    monkeypatch.setattr(image_tool, "get_storage", object)
    monkeypatch.setattr(image_tool.file_service, "direct_upload", fake_upload)
    monkeypatch.setattr(image_tool.billing, "charge_images", fake_charge)

    owner = uuid4()
    run_id = uuid4()
    tool = image_tool.make_generate_image(
        _empty_session,  # type: ignore[arg-type]
        owner_id=owner,
        settings=SimpleNamespace(),
        run_id=lambda: run_id,
        image_model_id=1,
    )
    ctx = _RecordingContext()

    result = await tool(ctx, "雪山日出", count=2)

    assert result["count"] == 2
    assert len(result["images"]) == 2
    assert set(result["images"][0]) == {
        "file_id",
        "name",
        "media_type",
        "size",
        "alt",
    }
    assert result["images"][0]["media_type"] == "image/png"
    assert result["images"][0]["size"] == len(b"png-bytes")
    assert result["images"][0]["alt"] == "雪山日出"

    assert len(ctx.events) == 2
    assert all(isinstance(event, ImageGeneratedEvent) for event in ctx.events)
    assert [event.file_id for event in ctx.events] == [
        entry["file_id"] for entry in result["images"]
    ]
    assert charged == [(owner, 2, run_id)]
