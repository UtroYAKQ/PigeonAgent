from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUserDep, CurrentUserDep, SessionDep, SettingsDep
from app.models.llm_model import LlmModel
from app.schemas.llm_model import LlmModelCreate, LlmModelList, LlmModelRead, LlmModelUpdate
from app.services import audit
from app.services import llm_model as model_service

router = APIRouter(prefix="/models", tags=["models"])


@router.post("", response_model=LlmModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: LlmModelCreate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> LlmModel:
    model = await model_service.create_model(db, payload, secret_key=settings.secret_key)
    await audit.record(
        actor=user,
        action=audit.MODEL_CREATE,
        target_type="model",
        target_id=str(model.id),
        detail={"name": model.name, "provider": model.provider},
    )
    return model


@router.get("", response_model=LlmModelList)
async def list_models(
    db: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LlmModelList:
    models, total = await model_service.list_models(db, limit=limit, offset=offset)
    return LlmModelList(items=[LlmModelRead.model_validate(model) for model in models], total=total)


@router.get("/{model_id}", response_model=LlmModelRead)
async def get_model(model_id: int, db: SessionDep, user: CurrentUserDep) -> LlmModel:
    return await model_service.get_model_or_404(db, model_id)


@router.patch("/{model_id}", response_model=LlmModelRead)
async def update_model(
    model_id: int,
    payload: LlmModelUpdate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> LlmModel:
    model = await model_service.update_model(db, model_id, payload, secret_key=settings.secret_key)
    await audit.record(
        actor=user,
        action=audit.MODEL_UPDATE,
        target_type="model",
        target_id=str(model.id),
        detail={"name": model.name, "provider": model.provider},
    )
    return model


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: int, db: SessionDep, user: AdminUserDep) -> None:
    model = await model_service.get_model_or_404(db, model_id)
    name = model.name
    await model_service.delete_model(db, model_id)
    await audit.record(
        actor=user,
        action=audit.MODEL_DELETE,
        target_type="model",
        target_id=str(model_id),
        detail={"name": name},
    )
