from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfigurationError, ConflictError, NotFoundError
from app.core.security import encrypt_secret
from app.models.llm_model import LlmModel
from app.schemas.llm_model import LlmModelCreate, LlmModelUpdate


async def list_models(
    session: AsyncSession, *, owner_id: UUID, limit: int, offset: int
) -> tuple[list[LlmModel], int]:
    total = await session.scalar(
        select(func.count()).select_from(LlmModel).where(LlmModel.owner_id == owner_id)
    )
    models = await session.scalars(
        select(LlmModel)
        .where(LlmModel.owner_id == owner_id)
        .order_by(LlmModel.id)
        .offset(offset)
        .limit(limit)
    )
    return list(models), total or 0


async def get_model_or_404(
    session: AsyncSession, model_id: int, *, owner_id: UUID
) -> LlmModel:
    model = await session.get(LlmModel, model_id)
    if model is None or model.owner_id != owner_id:
        raise NotFoundError(f"Model {model_id} not found")
    return model


async def create_model(
    session: AsyncSession, payload: LlmModelCreate, *, owner_id: UUID, secret_key: str | None
) -> LlmModel:
    values = payload.model_dump(exclude={"api_key"})
    values["provider"] = payload.provider.value
    values["owner_id"] = owner_id
    values["api_key_encrypted"] = _encrypt_api_key(payload.api_key, secret_key)
    if payload.is_default:
        await _clear_defaults(session, owner_id=owner_id)

    model = LlmModel(**values)
    session.add(model)
    await _commit_or_conflict(session, model.name)
    await session.refresh(model)
    return model


async def update_model(
    session: AsyncSession,
    model_id: int,
    payload: LlmModelUpdate,
    *,
    owner_id: UUID,
    secret_key: str | None,
) -> LlmModel:
    model = await get_model_or_404(session, model_id, owner_id=owner_id)
    data = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    if payload.provider is not None:
        data["provider"] = payload.provider.value
    if "api_key" in payload.model_fields_set:
        data["api_key_encrypted"] = _encrypt_api_key(payload.api_key, secret_key)
    if data.get("is_default") is True:
        await _clear_defaults(session, owner_id=owner_id)

    for field_name, value in data.items():
        setattr(model, field_name, value)
    await _commit_or_conflict(session, model.name)
    await session.refresh(model)
    return model


async def delete_model(session: AsyncSession, model_id: int, *, owner_id: UUID) -> None:
    model = await get_model_or_404(session, model_id, owner_id=owner_id)
    await session.delete(model)
    await session.commit()


def _encrypt_api_key(api_key: SecretStr | None, secret_key: str | None) -> str | None:
    if api_key is None:
        return None
    if secret_key is None:
        raise ConfigurationError("SECRET_KEY is required to store API keys")
    return encrypt_secret(api_key.get_secret_value(), secret_key)


async def _clear_defaults(session: AsyncSession, *, owner_id: UUID) -> None:
    await session.execute(
        update(LlmModel)
        .where(LlmModel.owner_id == owner_id, LlmModel.is_default.is_(True))
        .values(is_default=False)
        .execution_options(synchronize_session="evaluate")
    )


async def _commit_or_conflict(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # 并发设置默认模型触发的是 uq_llm_models_owner_single_default，不是重名
        if exc.orig is not None and "single_default" in str(exc.orig):
            raise ConflictError("Only one default model is allowed") from exc
        raise ConflictError(f"Model name '{name}' already exists") from exc
