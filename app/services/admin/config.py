"""应用配置项：代码里定义规格，数据库存显式覆盖。

- 配置项的类型、分组、是否密钥都定义在 ``CONFIG_SPECS`` 里，避免库里的元数据被改坏。
- 每次启动把环境变量里显式配置、而数据库里还没有值的配置项导入数据库；数据库已有值时以数据库为准。
- 生效优先级：数据库 > 环境变量 > 代码默认。``value`` 为 NULL 表示没有数据库覆盖，
  继续读环境变量；环境变量没配时回落 ``Settings`` 的代码默认值。
- 密钥配置用 SECRET_KEY 加密入库，读取时再解密给运行时使用，接口永远不回显明文。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.config.specs import CATEGORY_LABELS, CONFIG_SPECS, SPEC_BY_KEY, ConfigSpec
from app.core.exceptions import ConfigurationError, NotFoundError, UnprocessableError
from app.core.security import decrypt_secret, encrypt_secret
from app.enums.config import ConfigValueType
from app.models.admin.config import AppConfig
from app.schemas.admin.config import AppConfigRead, PublicConfigRead

logger = logging.getLogger(__name__)

ENV_IMPORT_MARKER = "__env_import_v1"


# --------------------------------------------------------------------- 解析


_TRUE_WORDS = {"true", "1", "yes", "on"}


def _to_text(spec: ConfigSpec, value: Any) -> str | None:
    """落库前归一成文本；按 value_type 解析时再转回各自的类型。"""
    if value is None:
        return None
    if spec.value_type is ConfigValueType.BOOLEAN:
        # 字符串不能按真假判断："false" 是非空字符串，会被误存成 "true"
        if isinstance(value, str):
            return "true" if value.strip().lower() in _TRUE_WORDS else "false"
        return "true" if value else "false"
    return str(value)


def _coerce_value(spec: ConfigSpec, raw: Any) -> Any:
    """按 value_type 解析并提交前的校验。

    入参可能是文本（表单）也可能是 JSON 原生类型（数字框、开关），两种都得吃下。
    """
    if spec.value_type is ConfigValueType.INTEGER:
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{spec.label} 必须是整数") from exc
    if spec.value_type is ConfigValueType.FLOAT:
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{spec.label} 必须是数字") from exc
    if spec.value_type is ConfigValueType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        lowered = str(raw).strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in {"false", "0", "no", "off", ""}:
            return False
        raise ValueError(f"{spec.label} 必须是 true 或 false")
    text = str(raw).strip()
    if spec.choices is not None and text not in spec.choices:
        raise ValueError(f"{spec.label} 只能是 {' / '.join(spec.choices)}")
    return text


def _decode_value(spec: ConfigSpec, raw: str, secret_key: str | None) -> Any:
    if spec.is_secret:
        if raw == "":
            return ""
        if not secret_key:
            raise ConfigurationError("解密配置项需要配置 SECRET_KEY")
        return decrypt_secret(raw, secret_key)
    return _coerce_value(spec, raw)


def _encode_value(spec: ConfigSpec, value: Any, secret_key: str | None) -> str | None:
    if not spec.is_secret:
        return _to_text(spec, value)
    text = str(value)
    if text == "":
        return ""
    if not secret_key:
        raise ConfigurationError("保存敏感配置需要配置 SECRET_KEY")
    return encrypt_secret(text, secret_key)


def _apply_overrides(base: Settings, overrides: dict[str, Any]) -> Settings:
    """逐项合并；库里的坏值只跳过自己，不回滚整份配置。"""
    effective = base
    for key, value in overrides.items():
        candidate = {**effective.model_dump(), key: value}
        try:
            effective = Settings.model_validate(candidate)
        except ValidationError as exc:
            message = exc.errors()[0].get("msg", "invalid value")
            logger.warning("Ignoring invalid config %s from database: %s", key, message)
    return effective


def _validate_value(spec: ConfigSpec, value: Any, base: Settings) -> None:
    try:
        Settings.model_validate({**base.model_dump(), spec.key: value})
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "配置值不合法")
        raise UnprocessableError(f"{spec.label}：{message}") from exc


def _inherited_source(spec: ConfigSpec, base: Settings) -> Literal["environment", "default"]:
    return "environment" if spec.key in base.model_fields_set else "default"


def _decode_or_inherit(spec: ConfigSpec, stored: str | None, base: Settings) -> tuple[Any, bool]:
    """返回 (生效值, 是否来自库里)。

    库里存了个解不开/类型不对的坏值时不抛错打断整份配置，退回环境值或代码默认值，
    但要在日志里留痕——否则管理员看到的"生效值"莫名其妙变了却无从排查。
    """
    if stored is None:
        return getattr(base, spec.key, None), False
    try:
        return _decode_value(spec, stored, base.secret_key), True
    except (ConfigurationError, ValueError):
        logger.warning("Invalid stored value for config %s; using environment", spec.key)
        return getattr(base, spec.key, None), False


def _seed_value(spec: ConfigSpec, base: Settings) -> str | None:
    """把环境变量值编码成可入库的值；代码默认值不落库。"""
    if spec.key not in base.model_fields_set:
        return None
    inherited = getattr(base, spec.key, None)
    if inherited is None or inherited == "":
        return None
    try:
        return _encode_value(spec, inherited, base.secret_key)
    except ConfigurationError:
        logger.warning("Cannot seed config %s from environment", spec.key)
        return None


# --------------------------------------------------------------------- 服务


async def seed_defaults(db: AsyncSession, base: Settings) -> None:
    """补齐配置行并同步元数据；库里缺值的配置项从环境变量补进来。"""
    rows = {row.key: row for row in await db.scalars(select(AppConfig))}
    changed = False
    # 清理早期版本的“只导入一次”标记行
    marker = rows.pop(ENV_IMPORT_MARKER, None)
    if marker is not None:
        await db.delete(marker)
        changed = True
    for order, spec in enumerate(CONFIG_SPECS):
        row = rows.get(spec.key)
        if row is None:
            db.add(
                AppConfig(
                    key=spec.key,
                    category=spec.category.value,
                    label=spec.label,
                    description=spec.description,
                    value_type=spec.value_type.value,
                    is_secret=spec.is_secret,
                    value=_seed_value(spec, base),
                    sort_order=order,
                )
            )
            changed = True
            continue
        metadata = {
            "category": spec.category.value,
            "label": spec.label,
            "description": spec.description,
            "value_type": spec.value_type.value,
            "is_secret": spec.is_secret,
            "sort_order": order,
        }
        for field, value in metadata.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        # 数据库没有值（首次建行或管理员撤销过）而环境变量有值时，启动即导入
        if row.value is None:
            seeded = _seed_value(spec, base)
            if seeded is not None:
                row.value = seeded
                changed = True
    if not changed:
        return
    try:
        await db.commit()
    except IntegrityError:
        # 多 worker 同时首启时可能撞唯一键；另一份 seed 已经写完了
        await db.rollback()
        logger.info("Configuration rows were seeded concurrently")


async def resolve_settings(db: AsyncSession, base: Settings) -> Settings:
    """把数据库覆盖值合并到当前 Settings 上；无覆盖时原样返回。"""
    rows = await db.scalars(select(AppConfig).where(AppConfig.value.is_not(None)))
    overrides: dict[str, Any] = {}
    for row in rows:
        spec = SPEC_BY_KEY.get(row.key)
        if spec is None:
            continue
        value, from_database = _decode_or_inherit(spec, row.value, base)
        if from_database:
            overrides[spec.key] = value
    return _apply_overrides(base, overrides)


def _to_read(row: AppConfig, base: Settings) -> AppConfigRead:
    spec = SPEC_BY_KEY[row.key]
    effective, from_database = _decode_or_inherit(spec, row.value, base)
    source: Literal["database", "environment", "default"] = (
        "database" if from_database else _inherited_source(spec, base)
    )
    return AppConfigRead(
        key=spec.key,
        category=spec.category.value,
        category_label=CATEGORY_LABELS[spec.category],
        label=spec.label,
        description=spec.description,
        value_type=spec.value_type,
        is_secret=spec.is_secret,
        choices=list(spec.choices) if spec.choices is not None else None,
        value=None if spec.is_secret else _to_text(spec, effective),
        has_value=effective is not None and effective != "",
        source=source,
        sort_order=row.sort_order,
    )


async def list_items(db: AsyncSession, base: Settings) -> list[AppConfigRead]:
    await seed_defaults(db, base)
    rows = await db.scalars(select(AppConfig).order_by(AppConfig.sort_order, AppConfig.id))
    return [_to_read(row, base) for row in rows if row.key in SPEC_BY_KEY]


async def update_item(
    db: AsyncSession, key: str, raw_value: str | int | float | bool | None, base: Settings
) -> AppConfigRead:
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise NotFoundError(f"Config '{key}' not found")
    await seed_defaults(db, base)
    row = await db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row is None:
        raise NotFoundError(f"Config '{key}' not found")

    if raw_value is None:
        row.value = None
    else:
        try:
            parsed = raw_value if spec.is_secret else _coerce_value(spec, raw_value)
        except ValueError as exc:
            raise UnprocessableError(str(exc)) from exc
        _validate_value(spec, parsed, base)
        row.value = _encode_value(spec, parsed, base.secret_key)

    await db.commit()
    return _to_read(row, base)


async def public_config(db: AsyncSession, base: Settings) -> PublicConfigRead:
    settings = await resolve_settings(db, base)
    return PublicConfigRead(
        site_name=settings.site_name,
        site_description=settings.site_description,
        site_logo_url=settings.site_logo_url,
        web_search_enabled=settings.can_use_web_search,
        email_verification_enabled=settings.is_email_verification_enabled,
    )
