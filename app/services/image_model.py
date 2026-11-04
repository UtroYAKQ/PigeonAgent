from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.infra.image_presets import preset_of
from app.models.image_model import ImageModel
from app.schemas.image_model import ImageModelCreate, ImageModelUpdate
from app.services import _model_catalog

# 与 LlmModel 同构：全局资源，写入权限由端点层的管理员依赖把关。
# 目录化 CRUD 的共用原语在 _model_catalog，本模块只留图片表特有的差异。

IMAGE_CATALOG = _model_catalog.ModelCatalog(cls=ImageModel, label="Image model")


async def list_models(db: AsyncSession, *, limit: int, offset: int) -> tuple[list[ImageModel], int]:
    return await _model_catalog.list_models(db, IMAGE_CATALOG, limit=limit, offset=offset)


async def get_model_or_404(db: AsyncSession, model_id: int) -> ImageModel:
    return await _model_catalog.get_model_or_404(db, IMAGE_CATALOG, model_id)


async def list_active_models(db: AsyncSession) -> list[ImageModel]:
    """默认模型排最前，其余按 id；列表小，前端一次取齐。"""
    rows = await db.scalars(select(ImageModel).where(ImageModel.is_active.is_(True)))
    return sorted(rows, key=lambda model: (not model.is_default, model.id))


async def get_active_model(db: AsyncSession, model_id: int | None = None) -> ImageModel | None:
    """取可用于生成的模型：指定 id 优先，否则默认，再否则第一个启用的。"""
    if model_id is not None:
        model = await db.get(ImageModel, model_id)
        return model if model is not None and model.is_active else None
    default = await db.scalar(
        select(ImageModel).where(ImageModel.is_default.is_(True), ImageModel.is_active.is_(True))
    )
    if default is not None:
        return default
    return await db.scalar(
        select(ImageModel).where(ImageModel.is_active.is_(True)).order_by(ImageModel.id)
    )


async def create_model(
    db: AsyncSession, payload: ImageModelCreate, *, secret_key: str | None
) -> ImageModel:
    values = payload.model_dump(exclude={"api_key"})
    values["provider"] = payload.provider.value
    values["protocol"] = (
        payload.protocol.value
        if payload.protocol is not None
        else preset_of(payload.provider.value).protocol.value
    )
    values["api_key_encrypted"] = _model_catalog.encrypt_api_key(payload.api_key, secret_key)
    if payload.is_default:
        await _model_catalog.clear_defaults(db, IMAGE_CATALOG)

    model = ImageModel(**values)
    db.add(model)
    await _model_catalog.commit_or_conflict(db, IMAGE_CATALOG, model.name)
    await db.refresh(model)
    return model


async def update_model(
    db: AsyncSession,
    model_id: int,
    payload: ImageModelUpdate,
    *,
    secret_key: str | None,
) -> ImageModel:
    model = await get_model_or_404(db, model_id)
    data = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    if payload.provider is not None:
        data["provider"] = payload.provider.value
    if payload.protocol is not None:
        data["protocol"] = payload.protocol.value
    elif payload.provider is not None:
        # 换供应商但没指定协议时，跟着预设走，避免旧协议配新地址
        data["protocol"] = preset_of(payload.provider.value).protocol.value
    if "api_key" in payload.model_fields_set:
        data["api_key_encrypted"] = _model_catalog.encrypt_api_key(payload.api_key, secret_key)
    # 只改一边时也要保证 default_size 落在 sizes 里
    if "sizes" in data or "default_size" in data:
        sizes = data.get("sizes", model.sizes)
        default_size = data.get("default_size", model.default_size)
        if default_size not in sizes:
            raise UnprocessableError("default_size must be one of sizes")
    if data.get("is_default") is True:
        await _model_catalog.clear_defaults(db, IMAGE_CATALOG)

    for field_name, value in data.items():
        setattr(model, field_name, value)
    await _model_catalog.commit_or_conflict(db, IMAGE_CATALOG, model.name)
    await db.refresh(model)
    return model


async def delete_model(db: AsyncSession, model_id: int) -> None:
    model = await get_model_or_404(db, model_id)
    await db.delete(model)
    await db.commit()
