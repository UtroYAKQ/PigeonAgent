"""图片工具：生成与读取。

生成工具不写 run content：每上传完一张就发 ImageGeneratedEvent，由 turn 落成 ImageItem；
读取工具把图片字节放进工具结果，由 turn 剥掉 base64 再落库，metadata 里只留文件引用。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from pydantic_ai import RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.events import ImageGeneratedEvent
from app.core.config import Settings
from app.domain.run_items import MEDIA_FILE_ID_KEY
from app.infra.image_factory import ImageGenerationError, create_client
from app.infra.storage import ObjectStorage, get_storage
from app.sandbox.workspace import RunWorkspace, parse_storage_key
from app.services import billing, file_service
from app.services import image_model as image_model_service

logger = logging.getLogger(__name__)

GenerateImageTool = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


def make_generate_image(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_id: UUID | None,
    settings: Settings,
    run_id: Callable[[], UUID | None],
    image_model_id: int | None = None,
) -> GenerateImageTool:
    """闭包捕获运行期依赖；工具签名只有模型看得懂的参数。"""

    async def generate_image(
        ctx: RunContext[Any],
        prompt: str,
        count: int = 1,
        size: str | None = None,
    ) -> dict[str, Any]:
        """根据文字描述生成图片，返回每张图的云端存储标识；结果会直接展示给用户。

        Args:
            prompt: 画面描述，尽量具体：主体、构图、光线、色调、风格。
            count: 生成几张，至少 1 张。
            size: 尺寸，取值见图片模型支持的档位，例如 1024x1024；留空用默认档位。
        """
        async with session_factory() as db:
            record = await image_model_service.get_active_model(db, image_model_id)
        if record is None:
            return {"error": "所选图片模型不可用；管理员还没有配置可用的图片模型。"}

        wanted = max(1, min(int(count or 1), record.max_images))
        chosen = size if size in record.sizes else record.default_size
        if size and size not in record.sizes:
            size_note = f"不支持的尺寸 {size}，已改用 {chosen}；可选：{', '.join(record.sizes)}"
        else:
            size_note = ""

        client = create_client(record, settings)
        try:
            images = await client.generate(prompt=prompt, size=chosen, count=wanted)
        except ImageGenerationError as exc:
            logger.warning("Image generation failed: %s", exc)
            return {"error": str(exc)}
        except Exception as exc:  # 上游五花八门的错误统一转成可读原因
            logger.exception("Image generation crashed")
            return {"error": f"生成失败：{exc.__class__.__name__}"}

        storage = get_storage()
        saved: list[dict[str, Any]] = []
        alt = prompt.strip()[:80]
        for image in images:
            name = f"generated-{uuid4().hex[:10]}.{_extension(image.media_type)}"
            async with session_factory() as db:
                file = await file_service.direct_upload(
                    db,
                    settings,
                    storage,
                    owner_id,
                    name,
                    image.media_type,
                    image.data,
                )
            storage_key = str(file.id)
            size_bytes = len(image.data)
            saved.append(
                {
                    "storage_key": storage_key,
                    "name": name,
                    "media_type": image.media_type,
                    "size": size_bytes,
                    "alt": alt,
                }
            )
            # 逐张通知 turn 落库并推给前端；工具本身不碰 run content
            await ctx.emit(
                ImageGeneratedEvent(
                    storage_key=storage_key,
                    file_name=name,
                    media_type=image.media_type,
                    size=size_bytes,
                    alt=alt,
                )
            )

        if owner_id is not None and saved:
            # 出图成功才扣；失败分支上游根本没给字节
            try:
                async with session_factory() as db:
                    await billing.charge_images(
                        db,
                        settings,
                        user_id=owner_id,
                        model=record,
                        count=len(saved),
                        run_id=run_id(),
                    )
            except Exception:
                logger.exception("Image billing failed for %s images", len(saved))

        result: dict[str, Any] = {
            "count": len(saved),
            "model": record.name,
            "size": chosen,
            "images": saved,
            "note": (
                "图片已经展示给用户，回复里不用再重复描述画面细节；"
                "需要读取图片内容时，把 storage_key 传给 read_image。"
            ),
        }
        if size_note:
            result["size_note"] = size_note
        return result

    return generate_image


def make_read_image(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_id: UUID | None,
    settings: Settings,
    storage: ObjectStorage,
    workspace: RunWorkspace | None,
) -> Callable[..., Coroutine[Any, Any, ToolReturn]]:
    """读取图片内容；接受 storage_key 或工作区相对路径，路径会先上传成文件引用。"""

    async def read_image(source: str) -> ToolReturn:
        """读取一张图片，把画面内容直接提供给你（支持 PNG/JPEG/WebP/GIF）。

        用于查看工具产物、上下文里的 <resource/> 引用或工作区里的图片文件；
        用户直接上传的图片已经能看见，不用重复调用。

        Args:
            source: 图片的 storage_key（<resource/> 里的值）或工作区相对路径，如 out/chart.png。
        """
        target = (source or "").strip()
        if not target:
            return _error("source 不能为空")

        file_id = parse_storage_key(target)
        if file_id is not None:
            try:
                async with session_factory() as db:
                    data, name, _, _ = await file_service.content_of(db, storage, owner_id, file_id)
            except Exception as exc:
                logger.warning("read_image failed for %s: %s", target, exc)
                return _error(_reason(exc))
            return _image_result(str(file_id), name, data, settings)

        if workspace is None:
            return _error("当前会话没有工作区，只能用 storage_key 读取图片")
        try:
            data = await workspace.read_binary(target, max_bytes=settings.max_upload_bytes)
        except Exception as exc:
            return _error(_reason(exc))

        media_type = _sniff_image_type(data)
        if media_type is None:
            return _error("不是受支持的图片格式；read_image 只读 PNG/JPEG/WebP/GIF")
        name = PurePosixPath(target.replace("\\", "/")).name or "image"
        try:
            async with session_factory() as db:
                record = await file_service.direct_upload(
                    db, settings, storage, owner_id, name, media_type, data
                )
        except Exception as exc:
            logger.warning("read_image upload failed for %s: %s", target, exc)
            return _error(_reason(exc))
        return _image_result(str(record.id), record.name, data, settings)

    return read_image


def _image_result(storage_key: str, name: str, data: bytes, settings: Settings) -> ToolReturn:
    media_type = _sniff_image_type(data)
    if media_type is None:
        return _error("不是受支持的图片格式；read_image 只读 PNG/JPEG/WebP/GIF")
    if len(data) > settings.max_upload_bytes:
        return _error(f"图片超过 {settings.max_upload_bytes // 1024 // 1024} MB 上限")
    return ToolReturn(
        return_value=[
            {
                "storage_key": storage_key,
                "name": name,
                "media_type": media_type,
                "size": len(data),
            },
            BinaryContent(data=data, media_type=media_type),
        ],
        metadata={MEDIA_FILE_ID_KEY: storage_key, "name": name, "media_type": media_type},
    )


def _error(message: str) -> ToolReturn:
    return ToolReturn(return_value={"error": message})


def _reason(exc: Exception) -> str:
    return (str(exc) or type(exc).__name__)[:500]


def _sniff_image_type(data: bytes) -> str | None:
    """按魔数判图，不信扩展名和入库时声明的 mime。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _extension(media_type: str) -> str:
    return {"image/jpeg": "jpg", "image/webp": "webp"}.get(media_type, "png")
