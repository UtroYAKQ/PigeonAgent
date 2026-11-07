"""应用配置：环境变量与数据库配置项的代码侧规格。"""

from app.core.config.settings import (
    DEFAULT_COMPACTION_THRESHOLD,
    WEAK_ADMIN_PASSWORDS,
    Settings,
    get_settings,
)

__all__ = [
    "DEFAULT_COMPACTION_THRESHOLD",
    "WEAK_ADMIN_PASSWORDS",
    "Settings",
    "get_settings",
]
