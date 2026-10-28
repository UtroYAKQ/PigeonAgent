from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PigeonAgent"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pigeon"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    secret_key: str | None = None
    llm_timeout_seconds: float = 60.0

    # S3 兼容对象存储：AWS S3 / 阿里云 OSS / MinIO / RustFS 共用一套配置，
    # 只有 endpoint_url 不同。全部可选，没配 bucket 就是未启用。
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    # 对象 key 的根前缀，多个环境共用一个桶时靠它隔开
    s3_prefix: str = "pigeon"
    # OSS 等只支持虚拟主机寻址的走 virtual；MinIO / RustFS 用 path
    s3_addressing_style: Literal["path", "virtual"] = "path"
    s3_presign_ttl_seconds: int = Field(default=600, ge=60, le=86_400)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)

    # 文件去重：blob 引用归零后的宽限期
    blob_grace_seconds: int = Field(default=86_400, ge=0)
    # GC 巡检间隔；0 表示不跑后台巡检，只留启动时的一次
    gc_interval_seconds: int = Field(default=3_600, ge=0)
    # presign 上传会话的有效期，超时未完成就等 GC 收尾
    upload_session_ttl_seconds: int = Field(default=7_200, ge=60)

    # e2b 兼容沙箱（阿里云 Agent Sandbox）：没配 key 就走本地临时文件夹。
    # api_url 形如 https://api.<region>.e2b.fc.aliyuncs.com，domain 是沙箱的域后缀。
    sandbox_api_key: str | None = None
    sandbox_api_url: str | None = None
    sandbox_domain: str | None = None
    sandbox_template: str = "code-interpreter-v1"
    # 无动静的沙箱等这么久就回收；中断等待期间同一个钟
    sandbox_idle_seconds: int = Field(default=600, ge=60)
    # 本地模式的工作区根目录；空着用系统临时目录
    workspace_root: str | None = None

    # JWT：access 短时效随请求走，refresh 长时效用于换发
    access_token_ttl_minutes: int = Field(default=30, ge=1)
    refresh_token_ttl_days: int = Field(default=7, ge=1)

    # 默认管理员：首启动且库里没有用户时自动种下
    admin_email: str = "admin@pigeon.local"
    admin_password: str = "admin123456"

    # SMTP（发件邮箱）；没配 host 就不发验证邮件
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_tls: Literal["none", "starttls", "ssl"] = "starttls"
    email_from: str = "PigeonAgent <no-reply@pigeon.local>"
    # 开了才有邮箱验证码环节；没配 SMTP 时自动当成关闭
    email_verification_required: bool = False

    @property
    def email_verification_enabled(self) -> bool:
        return bool(self.smtp_host) and self.email_verification_required

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: list[str]) -> list[str]:
        # allow_credentials=True 与通配符组合非法，必须显式列出来源
        if "*" in value:
            raise ValueError("cors_origins cannot contain '*'; list explicit origins")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
