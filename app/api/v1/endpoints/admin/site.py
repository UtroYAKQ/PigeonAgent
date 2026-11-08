from __future__ import annotations

from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import AdminUserDep, EnvSettingsDep, SessionDep
from app.core.exceptions import UnprocessableError
from app.domain.media.media_type import effective_media_type
from app.infra.files.storage import ObjectStorage, get_storage
from app.schemas.admin.config import SiteLogoRead
from app.services import site as site_service
from app.services.admin import audit
from app.services.admin import config as config_service

router = APIRouter(prefix="/site", tags=["site"])
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


@router.post("/logo", response_model=SiteLogoRead)
async def upload_logo(
    db: SessionDep,
    settings: EnvSettingsDep,
    storage: StorageDep,
    user: AdminUserDep,
    file: Annotated[UploadFile, File()],
) -> SiteLogoRead:
    if file.size is not None and file.size > site_service.MAX_LOGO_BYTES:
        raise UnprocessableError("站点 Logo 不能超过 2 MB")
    body = await file.read()
    if not body:
        raise UnprocessableError("空文件不能作为站点 Logo")
    if len(body) > site_service.MAX_LOGO_BYTES:
        raise UnprocessableError("站点 Logo 不能超过 2 MB")
    media_type = effective_media_type(file.filename, file.content_type, body)
    if media_type not in site_service.ALLOWED_LOGO_TYPES:
        raise UnprocessableError("站点 Logo 只支持 PNG、JPEG、WebP 或 GIF")

    await storage.put(site_service.logo_key(settings), body, media_type)
    url = site_service.logo_url(settings, body)
    await config_service.update_item(db, "site_logo_url", url, settings)
    await audit.record(
        actor=user,
        action=audit.CONFIG_UPDATE,
        target_type="config",
        target_id="site_logo_url",
        detail={"key": "site_logo_url"},
    )
    return SiteLogoRead(site_logo_url=url)


@router.delete("/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_logo(
    db: SessionDep,
    settings: EnvSettingsDep,
    storage: StorageDep,
    user: AdminUserDep,
) -> None:
    # 对象删除失败也要允许清配置，否则一个坏存储会把管理员卡死
    with suppress(Exception):
        await storage.delete(site_service.logo_key(settings))
    await config_service.update_item(db, "site_logo_url", None, settings)
    await audit.record(
        actor=user,
        action=audit.CONFIG_UPDATE,
        target_type="config",
        target_id="site_logo_url",
        detail={"key": "site_logo_url"},
    )
