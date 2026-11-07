"""全局模型目录（llm_models / image_models）共有的 CRUD 原语。

两张表同构：分页列表、按 id 取、清默认位、提交冲突翻译、API Key 加密这几步
只差映射类和错误文案前缀，差异全部收在 ModelCatalog 描述符里，不再各抄一份。
端点仍从 app.services.model.llm / app.services.model.image 进入，本模块只被
那两个服务调用，不是独立入口。
"""

from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfigurationError, ConflictError, NotFoundError
from app.core.security import encrypt_secret


@dataclass(frozen=True, slots=True)
class ModelCatalog[ModelT]:
    """一张全局模型表在目录化 CRUD 里的身份：映射类 + 错误文案前缀。

    label 只影响文案：NotFoundError/重名冲突用原文（"Model"/"Image model"），
    single_default 冲突用小写形式，与两张表既有报错逐字一致。
    """

    cls: type[ModelT]
    label: str


async def list_models[ModelT](
    db: AsyncSession, catalog: ModelCatalog[ModelT], *, limit: int, offset: int
) -> tuple[list[ModelT], int]:
    table: Any = catalog.cls
    total = await db.scalar(select(func.count()).select_from(table))
    models = await db.scalars(select(table).order_by(table.id).offset(offset).limit(limit))
    return list(models), total or 0


async def get_model_or_404[ModelT](
    db: AsyncSession, catalog: ModelCatalog[ModelT], model_id: int
) -> ModelT:
    model = await db.get(catalog.cls, model_id)
    if model is None:
        raise NotFoundError(f"{catalog.label} {model_id} not found")
    return model


def encrypt_api_key(api_key: SecretStr | None, secret_key: str | None) -> str | None:
    if api_key is None:
        return None
    if secret_key is None:
        raise ConfigurationError("保存 API Key 需要配置 SECRET_KEY")
    return encrypt_secret(api_key.get_secret_value(), secret_key)


async def clear_defaults(db: AsyncSession, catalog: ModelCatalog[Any]) -> None:
    table: Any = catalog.cls
    await db.execute(
        update(table)
        .where(table.is_default.is_(True))
        .values(is_default=False)
        .execution_options(synchronize_session="evaluate")
    )


async def commit_or_conflict(db: AsyncSession, catalog: ModelCatalog[Any], name: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # 并发设置默认模型触发的是 uq_{表名}_single_default 唯一索引，不是重名
        if exc.orig is not None and "single_default" in str(exc.orig):
            raise ConflictError(f"Only one default {catalog.label.lower()} is allowed") from exc
        raise ConflictError(f"{catalog.label} name '{name}' already exists") from exc
