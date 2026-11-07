"""模型/工具内容的 JSON 与媒体整形。"""

from __future__ import annotations

import base64
import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    FileUrl,
    ImageUrl,
    TextContent,
    VideoUrl,
)


def to_json_value(value: Any) -> Any:
    """把 dataclass / pydantic 模型 / 普通值转成可 JSON 序列化的结构。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if hasattr(value, "model_dump"):
        return to_json_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def content_to_json(content: Any) -> Any:
    """模型/工具内容转成可存储且能还原的结构。

    bytes 直接走 to_json_value 会变成 ``b'\\x89...'`` 字符串，回放上下文时图就废了，
    所以媒体单独打标成 media 结构。
    """
    if content is None or isinstance(content, (str, int, float, bool)):
        return content
    if isinstance(content, BinaryContent):
        return {
            "media": "binary",
            "media_type": str(content.media_type),
            "data": base64.b64encode(content.data).decode("ascii"),
        }
    if isinstance(content, FileUrl):
        for kind, url_type in _URL_BY_KIND.items():
            if isinstance(content, url_type):
                return {"media": kind, "url": content.url}
        return {"media": "document-url", "url": content.url}
    if isinstance(content, TextContent):
        return content.content
    if isinstance(content, Mapping):
        return {str(key): content_to_json(item) for key, item in content.items()}
    if isinstance(content, Sequence):
        return [content_to_json(element) for element in content]
    return to_json_value(content)


def content_from_json(value: Any) -> Any:
    """``content_to_json`` 的逆变换；普通内容原样返回。"""
    if isinstance(value, list):
        return [content_from_json(element) for element in value]
    if isinstance(value, dict):
        kind = value.get("media")
        if kind == "binary":
            return BinaryContent(
                data=base64.b64decode(value["data"]), media_type=value["media_type"]
            )
        url_type = _URL_BY_KIND.get(kind) if isinstance(kind, str) else None
        if url_type is not None:
            return url_type(url=value["url"])
        return {str(key): content_from_json(item) for key, item in value.items()}
    return value


_URL_BY_KIND: dict[str, type[FileUrl]] = {
    "image-url": ImageUrl,
    "video-url": VideoUrl,
    "audio-url": AudioUrl,
    "document-url": DocumentUrl,
}

_DROPPED = object()


def _without_binary(value: Any) -> Any:
    if isinstance(value, BinaryContent):
        return _DROPPED
    if isinstance(value, list):
        return [kept for item in value if (kept := _without_binary(item)) is not _DROPPED]
    if isinstance(value, dict):
        if value.get("media") == "binary":
            return _DROPPED
        return {
            key: kept
            for key, item in value.items()
            if (kept := _without_binary(item)) is not _DROPPED
        }
    return value


def without_binary_media(content: Any) -> Any:
    """落库/上报前剥掉工具结果里的 base64 图片；引用留在 ToolResultItem.media。"""
    stripped = _without_binary(content)
    return None if stripped is _DROPPED else stripped


def has_failure_report(content: Any) -> bool:
    """工具正常返回但结果体宣告失败：error / 非零 exit_code / ok=false。

    公开给「只想知道成没成」的调用方：不必为此构造一个 ToolResultItem。
    """
    value = content
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith(("{", "[")):
            return False
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return False
    if not isinstance(value, dict):
        return False
    error = value.get("error")
    if isinstance(error, str) and error.strip():
        return True
    exit_code = value.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return True
    return value.get("ok") is False
