from fastapi import APIRouter

from app.api.deps import AdminUserDep, EnvSettingsDep, OperationLoggerDep, SessionDep
from app.schemas.app_config import (
    AppConfigList,
    AppConfigRead,
    AppConfigUpdate,
    PublicConfigRead,
)
from app.services import app_config as config_service
from app.services import audit

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("/public", response_model=PublicConfigRead)
async def public_config(db: SessionDep, settings: EnvSettingsDep) -> PublicConfigRead:
    """登录页/公开分享页可读的站点信息，不需要登录。"""
    return await config_service.public_config(db, settings)


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
