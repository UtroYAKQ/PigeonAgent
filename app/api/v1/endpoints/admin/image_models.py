from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUserDep, CurrentUserDep, SessionDep, SettingsDep
from app.infra.providers.presets import PROVIDER_PRESETS
from app.models.ai.image import ImageModel
from app.schemas.model.image import (
    ImageModelCreate,
    ImageModelList,
    ImageModelRead,
    ImageModelUpdate,
    ImageProviderRead,
)
from app.services.admin import audit
from app.services.model import image as image_model_service

router = APIRouter(prefix="/image-models", tags=["image-models"])


@router.post("", response_model=ImageModelRead, status_code=status.HTTP_201_CREATED)
async def create_image_model(
    payload: ImageModelCreate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> ImageModel:
    model = await image_model_service.create_model(db, payload, secret_key=settings.secret_key)
    await audit.record(
        actor=user,
        action=audit.IMAGE_MODEL_CREATE,
        target_type="image_model",
        target_id=str(model.id),
        detail={"name": model.name, "provider": model.provider},
    )
    return model


@router.get("/providers", response_model=list[ImageProviderRead])
async def list_image_providers(user: CurrentUserDep) -> list[ImageProviderRead]:
    """供应商预设；选中后前端自动带出地址与尺寸档。"""
    return [
        ImageProviderRead(
            key=preset.key.value,
            label=preset.label,
            protocol=preset.protocol,
            base_url=preset.base_url,
            path=preset.path,
            model_hint=preset.model_hint,
            sizes=list(preset.sizes),
            note=preset.note,
        )
        for preset in PROVIDER_PRESETS
    ]


@router.get("", response_model=ImageModelList)
async def list_image_models(
    db: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ImageModelList:
    models, total = await image_model_service.list_models(db, limit=limit, offset=offset)
    return ImageModelList(
        items=[ImageModelRead.model_validate(model) for model in models], total=total
    )


@router.get("/{model_id}", response_model=ImageModelRead)
async def get_image_model(model_id: int, db: SessionDep, user: CurrentUserDep) -> ImageModel:
    return await image_model_service.get_model_or_404(db, model_id)


@router.patch("/{model_id}", response_model=ImageModelRead)
async def update_image_model(
    model_id: int,
    payload: ImageModelUpdate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> ImageModel:
    model = await image_model_service.update_model(
        db, model_id, payload, secret_key=settings.secret_key
    )
    await audit.record(
        actor=user,
        action=audit.IMAGE_MODEL_UPDATE,
        target_type="image_model",
        target_id=str(model.id),
        detail={"name": model.name, "provider": model.provider},
    )
    return model


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image_model(model_id: int, db: SessionDep, user: AdminUserDep) -> None:
    model = await image_model_service.get_model_or_404(db, model_id)
    name = model.name
    await image_model_service.delete_model(db, model_id)
    await audit.record(
        actor=user,
        action=audit.IMAGE_MODEL_DELETE,
        target_type="image_model",
        target_id=str(model_id),
        detail={"name": name},
    )
