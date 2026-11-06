"""publish_file 的产物事件：typed payload、turn 落 ResourceItem、不进上下文。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic_ai.messages import FunctionToolResultEvent, ToolReturnPart

from app import codec
from app.agents.events import ArtifactEvent, ArtifactMedia
from app.agents.turn import AgentTurn
from app.domain.run_items import ResourceItem, ToolResultItem


class _RecordingStore:
    def __init__(self) -> None:
        self.appended: list[Any] = []
        self.flushes = 0

    async def append_items(self, items: list[Any], *, usage: Any = None) -> list[Any]:
        self.appended.extend(items)
        return list(items)

    async def flush(self) -> None:
        self.flushes += 1


def _event(file_id: str) -> ArtifactEvent:
    return ArtifactEvent(
        media=[
            ArtifactMedia(
                file_id=file_id,
                name="sea_day.png",
                media_type="image/png",
                size=1024,
            )
        ]
    )


async def test_artifact_event_persists_display_only_resource() -> None:
    """事件是唯一落库来源；产物只服务历史/前端，不进上下文。"""
    file_id = str(uuid.uuid4())
    store = _RecordingStore()
    turn = AgentTurn(object(), store, None)  # type: ignore[arg-type]

    await turn._on_artifact(_event(file_id))

    [item] = store.appended
    assert isinstance(item, ResourceItem)
    assert item.role == "assistant"
    assert item.file_id == file_id
    assert item.name == "sea_day.png"
    assert item.media_type == "image/png"
    assert item.size == 1024
    assert item.in_context is False
    assert store.flushes == 1
    assert codec.messages_from_items([item]) == []


def test_artifact_event_payload_matches_frontend_shape() -> None:
    """to_payload 保持前端现有的 media[{...}] 形状。"""
    file_id = str(uuid.uuid4())
    assert _event(file_id).to_payload() == {
        "media": [
            {
                "file_id": file_id,
                "name": "sea_day.png",
                "media_type": "image/png",
                "size": 1024,
                "alt": None,
                "origin": "workspace",
            }
        ]
    }


def test_assistant_resource_never_renders_as_user_content() -> None:
    """即使有人忘了 in_context=False，assistant 产物也不能冒充用户内容。"""
    item = ResourceItem(
        role="assistant",
        file_id=str(uuid.uuid4()),
        name="a.pdf",
    )
    assert codec.messages_from_items([item]) == []


def test_user_resource_still_renders_tag() -> None:
    key = str(uuid.uuid4())
    item = ResourceItem(role="user", file_id=key, name="a.pdf")
    message = codec.messages_from_items([item])[-1]
    content = message.parts[0].content
    assert isinstance(content, str) and key in content


async def test_publish_tool_result_only_persists_tool_result() -> None:
    """工具结果只落 ToolResultItem；ResourceItem 不再从结果体二次解析。"""
    file_id = str(uuid.uuid4())
    event = FunctionToolResultEvent(
        part=ToolReturnPart(
            tool_name="publish_file",
            tool_call_id="call_1",
            content={
                "file_id": file_id,
                "name": "sea_day.png",
                "size": 1024,
                "media_type": "image/png",
            },
        )
    )
    store = _RecordingStore()
    turn = AgentTurn(object(), store, None)  # type: ignore[arg-type]

    await turn._on_tool_result(event)

    assert len(store.appended) == 1
    assert isinstance(store.appended[0], ToolResultItem)
