"""图片生成工具：调用图片模型出图，每张立刻落库并推给前端。

和联网搜索一样是普通 function tool，区别在于它有两个副作用：
把图片写成 FileRecord（前端按 file_id 取字节），以及往 run 里追加 ImageItem。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.events import ArtifactEvent
from app.agents.store import SessionStore
from app.core.config import Settings
from app.domain.run_items import ImageItem
from app.infra.image_factory import ImageGenerationError, create_client
from app.infra.storage import get_storage
from app.services import billing, file_service
from app.services import image_model as image_model_service

logger = logging.getLogger(__name__)

GenerateImageTool = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


def make_generate_image(
    store: SessionStore,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_id: UUID | None,
    settings: Settings,
    image_model_id: int | None = None,
) -> GenerateImageTool:
    """闭包捕获运行期依赖；工具签名只有模型看得懂的参数。"""

    async def generate_image(
        prompt: str,
        count: int = 1,
        size: str | None = None,
    ) -> dict[str, Any]:
        """根据文字描述生成图片，生成结果会直接展示给用户。

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
            item = ImageItem(
                role="assistant",
                file_id=str(file.id),
                media_type=image.media_type,
                alt=alt,
                # 图片字节不进模型上下文：模型已经知道生成结果了
                in_context=False,
            )
            await store.append_items([item])
            # 逐张落库，取消或失败时已出的图不会丢
            await store.flush()
            payload = {
                "file_id": str(file.id),
                "media_type": image.media_type,
                "name": name,
                "size": len(image.data),
                "alt": alt,
                "origin": "generated",
            }
            saved.append(payload)
            store.emit(ArtifactEvent(media=[payload]))

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
                        run_id=store.run_uuid,
                    )
            except Exception:
                logger.exception("Image billing failed for %s images", len(saved))

        result: dict[str, Any] = {
            "count": len(saved),
            "model": record.name,
            "size": chosen,
            "note": "图片已经展示给用户，回复里不用再重复描述画面细节。",
        }
        if size_note:
            result["size_note"] = size_note
        return result

    return generate_image


def _extension(media_type: str) -> str:
    return {"image/jpeg": "jpg", "image/webp": "webp"}.get(media_type, "png")
