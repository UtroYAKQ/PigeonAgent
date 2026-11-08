from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import (
    AdminUserDep,
    EnvSettingsDep,
    OperationLoggerDep,
    SessionDep,
    SettingsDep,
)
from app.core.exceptions import NotFoundError
from app.domain.media.media_type import detect_media_type
from app.infra.files.storage import ObjectStorage, get_storage
from app.schemas.admin.config import (
    AppConfigList,
    AppConfigRead,
    AppConfigUpdate,
    PublicConfigRead,
)
from app.services import site as site_service
from app.services.admin import audit
from app.services.admin import config as config_service

router = APIRouter(prefix="/configs", tags=["configs"])
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


@router.get("/public", response_model=PublicConfigRead)
async def public_config(db: SessionDep, settings: EnvSettingsDep) -> PublicConfigRead:
    """登录页/公开分享页可读的站点信息，不需要登录。"""
    return await config_service.public_config(db, settings)


@router.get("/public/logo")
async def public_logo(settings: SettingsDep, storage: StorageDep) -> Response:
    """站点 Logo 是公开资源，不走用户鉴权；URL 带内容 hash 可长期缓存。"""
    try:
        data = await storage.get(site_service.logo_key(settings))
    except Exception as exc:
        raise NotFoundError("站点 Logo 未配置") from exc
    media_type = detect_media_type("site-logo", data)
    if media_type not in site_service.ALLOWED_LOGO_TYPES:
        raise NotFoundError("站点 Logo 未配置")
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("", response_model=AppConfigList)
async def list_configs(
    db: SessionDep, settings: EnvSettingsDep, user: AdminUserDep
) -> AppConfigList:
    items = await config_service.list_items(db, settings)
    return AppConfigList(items=items, total=len(items))


@router.patch("/{key}", response_model=AppConfigRead)
async def update_config(
    key: str,
    payload: AppConfigUpdate,
    db: SessionDep,
    settings: EnvSettingsDep,
    user: AdminUserDep,
    operation_logger: OperationLoggerDep,
) -> AppConfigRead:
    updated = await config_service.update_item(db, key, payload.value, settings)
    await audit.record(
        actor=user,
        action=audit.CONFIG_UPDATE,
        target_type="config",
        target_id=key,
        detail={"key": key},
    )
    # 日志的限长与排除路径也在这张表里：改完当场生效，不用等重启
    if operation_logger is not None:
        operation_logger.configure(await config_service.resolve_settings(db, settings))
    return updated
