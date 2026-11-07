from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.enums.config import ConfigValueType


class AppConfigRead(BaseModel):
    key: str
    category: str
    category_label: str
    label: str
    description: str | None
    value_type: ConfigValueType
    is_secret: bool
    # 枚举型配置的可选值（如 smtp_tls）
    choices: list[str] | None
    # 非密钥配置直接给当前生效值；密钥永远不回显
    value: str | None
    # 当前是否有生效值（密钥也能据此判断是否已配置）
    has_value: bool
    # database=数据库显式覆盖；environment=环境变量；default=代码默认
    source: Literal["database", "environment", "default"]
    sort_order: int


class AppConfigList(BaseModel):
    items: list[AppConfigRead]
    total: int


class AppConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null 表示撤销覆盖，回落到环境变量。
    # 数字/布尔输入框交给客户端时是 JSON 原生类型，这里一律收下再按 value_type 归一，
    # 只认字符串的话管理员填端口就会撞上 "Input should be a valid string"。
    value: str | int | float | bool | None


class PublicConfigRead(BaseModel):
    site_name: str
    site_description: str
    site_logo_url: str | None
    web_search_enabled: bool
    email_verification_enabled: bool
