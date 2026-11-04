from enum import StrEnum


class ConfigCategory(StrEnum):
    """配置项分组。"""

    SITE = "site"
    DEEPSEEK = "deepseek"
    SANDBOX = "sandbox"
    EMAIL = "email"
    FILES = "files"
    LOGGING = "logging"
    # 平台级功能总闸：和凭证分开，关掉不必删 key
    FEATURES = "features"
    BILLING = "billing"


class ConfigValueType(StrEnum):
    """配置项的值类型；入库统一存文本，读取时按这里解析。"""

    STRING = "string"
    SECRET = "secret"
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
