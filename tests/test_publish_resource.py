from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from app import codec
from app.domain.run_items import ResourceItem


def _return_part(tool_name: str, content: Any) -> ToolReturnPart:
    return ToolReturnPart(
        tool_name=tool_name,
        content=content,
        tool_call_id="call-1",
    )


def test_publish_result_becomes_an_assistant_resource() -> None:
    """publish_file 的结果必须落成 item，否则前端没有任何可渲染的东西。"""
    item = codec.published_resource(
        _return_part(
            "publish_file",
            {
                "storage_key": "abc-123",
                "name": "sea_day.png",
                "size": 1024,
                "media_type": "image/png",
            },
        )
    )

    assert isinstance(item, ResourceItem)
    assert item.role == "assistant"
    assert item.storage_key == "abc-123"
    assert item.name == "sea_day.png"
    assert item.media_type == "image/png"
    assert item.size == 1024


def test_failed_publish_does_not_create_a_resource() -> None:
    """失败时工具返回 {"error": ...}，不该凭空造出一个空卡片。"""
    assert codec.published_resource(_return_part("publish_file", {"error": "存储未启用"})) is None


def test_other_tools_are_ignored() -> None:
    content = {"storage_key": "abc-123", "name": "x"}
    assert codec.published_resource(_return_part("read_file", content)) is None


def test_malformed_result_is_ignored() -> None:
    assert codec.published_resource(_return_part("publish_file", "not a dict")) is None
    assert codec.published_resource(_return_part("publish_file", {"storage_key": ""})) is None
    # 非 ToolReturnPart（例如重试提示）不该被当成发布成功
    assert (
        codec.published_resource(
            ToolCallPart(tool_name="publish_file", args={}, tool_call_id="c1")  # type: ignore[arg-type]
        )
        is None
    )
