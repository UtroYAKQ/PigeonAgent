from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.models.llm_model import LlmModel
from app.schemas.llm_model import LlmModelCreate, LlmModelList, LlmModelRead, LlmModelUpdate
from app.services import llm_model as model_service

router = APIRouter(prefix="/models", tags=["models"])


@router.post("", response_model=LlmModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: LlmModelCreate,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
) -> LlmModel:
    return await model_service.create_model(
        session, payload, owner_id=user.id, secret_key=settings.secret_key
    )


@router.get("", response_model=LlmModelList)
async def list_models(
    session: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LlmModelList:
    models, total = await model_service.list_models(
        session, owner_id=user.id, limit=limit, offset=offset
    )
    return LlmModelList(items=[LlmModelRead.model_validate(model) for model in models], total=total)


@router.get("/{model_id}", response_model=LlmModelRead)
async def get_model(model_id: int, session: SessionDep, user: CurrentUserDep) -> LlmModel:
    return await model_service.get_model_or_404(session, model_id, owner_id=user.id)


@router.patch("/{model_id}", response_model=LlmModelRead)
async def update_model(
    model_id: int,
    payload: LlmModelUpdate,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
) -> LlmModel:
    return await model_service.update_model(
        session, model_id, payload, owner_id=user.id, secret_key=settings.secret_key
    )


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    await model_service.delete_model(session, model_id, owner_id=user.id)
