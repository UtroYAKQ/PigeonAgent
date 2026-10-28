"""资源链路的编解码与 schema 校验：ResourceItem 渲染、RunCreate.resources、转换兜底。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic_ai.messages import UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.schemas import run_item
from app.schemas.run import ResourceRef, RunCreate
from app.services import file_service
from app.services.item_codec import item_text, messages_from_items
from tests.test_files import FakeStorage

BODY = b"resource payload"


async def _seed_file(db: AsyncSession, name: str = "note.md", mime: str | None = None) -> Any:
    fake = FakeStorage()
    settings = Settings(secret_key="x" * 44)
    file = await file_service.direct_upload(db, settings, fake, None, name, mime, BODY)
    return file, fake


async def test_resource_item_renders_tag_in_user_content(db_session: AsyncSession) -> None:
    record, _ = await _seed_file(db_session, "note.md", "text/markdown")
    # hint 留空：名字与 mime 都取自入库记录
    item = run_item.resource_items([(record, None)])[0]
    key = str(record.id)
    assert item_text(item) == item.name  # 检索文本只是名字；完整标签在消息里
    assert item.name == "note.md" and item.media_type == "text/markdown"
    # messages_from_items 走 pydantic-ai 消息：user 的 resource 渲染成 <resource/> 标签
    request = messages_from_items([item])[-1]
    parts_text = "\n".join(str(part.content) for part in request.parts)
    assert key in parts_text
    assert 'original_name="note.md"' in parts_text
    assert 'mime_type="text/markdown"' in parts_text

def test_run_create_accepts_and_validates_resources() -> None:
    key = str(uuid.uuid4())
    payload = RunCreate.model_validate(
        {
            "input": "分析这个文件",
            "resources": [{"storage_key": key, "name": "a.md"}],
        }
    )
    assert payload.resources[0].name == "a.md"

    try:
        RunCreate.model_validate(
            {
                "input": "x",
                "resources": [{"storage_key": "not-a-uuid", "name": "a.md"}],
            }
        )
    except Exception as exc:
        assert "storage_key" in str(exc)
    else:
        raise AssertionError("非法 storage_key 应当被拒")


async def test_resource_items_for_resolves_and_errors(
    db_session: AsyncSession,
) -> None:
    record, _ = await _seed_file(db_session, "main.md", "text/markdown")
    key = str(record.id)
    missing = str(uuid.uuid4())

    items = await file_service.resource_items_for(
        db_session, [ResourceRef(storage_key=key)]
    )
    assert len(items) == 1
    assert items[0].name == "main.md"  # 命名以库里为准，不用调用方伪造

    try:
        await file_service.resource_items_for(
            db_session,
            [ResourceRef(storage_key=missing)],
        )
    except Exception as exc:
        assert missing in str(exc)
    else:
        raise AssertionError("缺失文件应该报而不是静默")


async def test_image_resource_becomes_image_item(db_session: AsyncSession) -> None:
    """图片引用落成 ImageItem(file_id)：上下文里是 <resource/> 标签 + 内联图片。"""
    record, fake = await _seed_file(db_session, "pic.png", "image/png")
    items = await file_service.resource_items_for(
        db_session, [ResourceRef(storage_key=str(record.id))]
    )
    assert len(items) == 1
    image = items[0]
    assert isinstance(image, run_item.ImageItem)
    assert image.file_id == str(record.id)
    assert image.data is None and image.url is None
    assert image.media_type == "image/png"

    media = await file_service.load_media(db_session, [image.file_id], storage=fake)
    request = messages_from_items([image], media=media)[-1]
    [prompt] = [part for part in request.parts if isinstance(part, UserPromptPart)]
    content = prompt.content
    assert isinstance(content, list) and len(content) == 2
    assert isinstance(content[0], str)
    assert f'storage_key="{record.id}"' in content[0]
    assert 'original_name="pic.png"' in content[0]
    assert content[1].media_type == "image/png"
    assert content[1].data


async def test_video_item_inlines_content_and_tag(db_session: AsyncSession) -> None:
    record, fake = await _seed_file(db_session, "clip.mp4", "video/mp4")
    video = run_item.VideoItem(
        role="user",
        file_id=str(record.id),
        alt="clip.mp4",
        media_type="video/mp4",
    )
    media = await file_service.load_media(db_session, [video.file_id], storage=fake)
    request = messages_from_items([video], media=media)[-1]
    [prompt] = [part for part in request.parts if isinstance(part, UserPromptPart)]
    tag, payload = prompt.content
    assert f'storage_key="{record.id}"' in tag and "video/mp4" in tag
    assert payload.media_type == "video/mp4"


async def test_image_item_missing_media_falls_back_to_tag(db_session: AsyncSession) -> None:
    """key 失效（没配存储/内容没了）只退化成标签，不打断整轮上下文。"""
    fid = str(uuid.uuid4())
    image = run_item.ImageItem(role="user", file_id=fid, alt="pic")
    request = messages_from_items([image], media={})[-1]
    [prompt] = [part for part in request.parts if isinstance(part, UserPromptPart)]
    assert isinstance(prompt.content, str)
    assert f'storage_key="{fid}"' in prompt.content


async def test_attachment_file_id_and_validation() -> None:
    """附件只认 file_id；base64 data 与 kind=file 都已移除。"""
    from app.services.item_codec import attachment_items

    fid = str(uuid.uuid4())
    att = {"kind": "video", "name": "p.mp4", "media_type": "video/mp4", "file_id": fid}
    [item] = attachment_items([run_item_attachment(att)])
    assert isinstance(item, run_item.VideoItem)
    assert item.file_id == fid and item.data is None

    # base64 兜底已删：data 是多余字段
    try:
        run_item_attachment(
            {"kind": "image", "name": "p.png", "media_type": "image/png", "data": "aGk="}
        )
    except Exception as exc:
        assert "file_id" in str(exc) and "data" in str(exc)
    else:
        raise AssertionError("data-only 附件应当被拒")

    # 文档不再走附件，kind 只剩 image/video
    try:
        run_item_attachment(
            {"kind": "file", "name": "a.md", "media_type": "text/plain", "file_id": fid}
        )
    except Exception as exc:
        assert "kind" in str(exc)
    else:
        raise AssertionError("kind=file 应当被拒")


async def test_resolve_attachments_normalizes_from_record(db_session: AsyncSession) -> None:
    """file_id 附件的 kind/name/mime 以入库记录为准，不信客户端自报。"""
    record, _ = await _seed_file(db_session, "pic.png", "image/png")
    spoofed = run_item_attachment(
        {
            "kind": "video",
            "name": "fake.mp4",
            "media_type": "video/mp4",
            "file_id": str(record.id),
        }
    )

    [normalized] = await file_service.resolve_attachments(db_session, [spoofed])
    assert normalized.kind == "image"
    assert normalized.name == "pic.png"
    assert normalized.media_type == "image/png"
    assert normalized.file_id == str(record.id)


async def test_resolve_attachments_rejects_bad_references(db_session: AsyncSession) -> None:
    record, _ = await _seed_file(db_session, "pic.png", "image/png")
    doc, _ = await _seed_file(db_session, "note.md", "text/markdown")

    async def fails(payload: dict[str, Any], needle: str, *, owner: Any = None) -> None:
        try:
            await file_service.resolve_attachments(
                db_session, [run_item_attachment(payload)], owner=owner
            )
        except Exception as exc:
            assert needle in str(exc)
        else:
            raise AssertionError(f"{needle} 应当报错")

    missing = str(uuid.uuid4())
    await fails(
        {"kind": "image", "name": "a.png", "media_type": "image/png", "file_id": missing},
        "不存在或已被删除",
    )
    # 非媒体文件不能冒充图片附件
    await fails(
        {"kind": "image", "name": "a.md", "media_type": "image/png", "file_id": str(doc.id)},
        "只支持图片或视频",
    )
    # 别人的文件同样按不存在处理
    other_owner = uuid.uuid4()
    foreign = await file_service.direct_upload(
        db_session, Settings(secret_key="x" * 44), FakeStorage(), other_owner, "theirs.png",
        "image/png", BODY,
    )
    await fails(
        {
            "kind": "image",
            "name": "t.png",
            "media_type": "image/png",
            "file_id": str(foreign.id),
        },
        "不存在或已被删除",
        owner=uuid.uuid4(),
    )
    # 匿名上传对谁都可见（和 downloads 的规则一致）
    [kept] = await file_service.resolve_attachments(
        db_session,
        [run_item_attachment(
            {
                "kind": "image",
                "name": "p.png",
                "media_type": "image/png",
                "file_id": str(record.id),
            }
        )],
        owner=uuid.uuid4(),
    )
    assert kept.file_id == str(record.id)


def run_item_attachment(payload: dict[str, Any]) -> Any:
    from app.schemas.run import Attachment

    return Attachment.model_validate(payload)

