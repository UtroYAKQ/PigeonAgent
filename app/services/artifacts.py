"""run 收尾的产物同步：工作区里写出的文件 → blob → ResourceItem。

Local 模式扫工作区目录，沙箱模式按工具记账的文件清单收；
上传走 direct_upload（内容去重），随后把 ResourceItem 追加进 run.content。
"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.schemas.run_item import ResourceItem
from app.services import file_service
from app.services import session_run as run_store
from app.services.storage import ObjectStorage
from app.services.workspace import RunWorkspace

logger = logging.getLogger(__name__)


async def sync_run_artifacts(
    workspace: RunWorkspace,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    session_id: UUID,
    run_id: UUID,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None = None,
) -> list[ResourceItem]:
    """把工作区的产物上传并登记成助手侧 ResourceItem；没有产物就空手回。"""
    try:
        artifacts = await workspace.collect_artifacts()
    except Exception:
        logger.exception("Failed to collect artifacts for run %s", run_id)
        return []
    if not artifacts:
        return []

    items: list[ResourceItem] = []
    async with session_factory() as db:
        for name, data, mime in artifacts[:50]:
            try:
                record = await file_service.direct_upload(
                    db, settings, storage, owner, name, mime, data
                )
            except Exception:
                # 单个产物失败不拖累整批；本地目录照常清，模型下一轮还能再写
                logger.exception("Failed to upload artifact %s for run %s", name, run_id)
                continue
            items.append(
                ResourceItem(
                    role="assistant",
                    storage_key=str(record.id),
                    name=record.name,
                    media_type=mime or "application/octet-stream",
                    size=record.size,
                )
            )
    if items:
        async with session_factory() as db:
            await run_store.append_items(db, session_id, run_id, items)
    return items

