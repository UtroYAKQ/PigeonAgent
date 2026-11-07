from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 出厂占位发件人：库里或 .env 里还是它，就当作"没配"，回落到 SMTP 账号
_PLACEHOLDER_FROM = "no-reply@pigeon.local"
_FALLBACK_FROM = f"PigeonAgent <{_PLACEHOLDER_FROM}>"

# 首次启动创建管理员时拒绝这些明显弱口令
DEFAULT_ADMIN_PASSWORD = "change-me"
WEAK_ADMIN_PASSWORDS = frozenset({"admin123456", DEFAULT_ADMIN_PASSWORD})

# 开跑前压缩的触发水位：估算上下文达到模型窗口的这个比例就先摘要。
# 可调（Settings.compaction_threshold），但默认值只在这里写一次，agent 各层共用。
DEFAULT_COMPACTION_THRESHOLD = 0.8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PigeonAgent"
    # 站点展示信息：公开接口下发给前端，管理员可在配置表里覆盖
    site_name: str = "PigeonAgent"
    site_description: str = "大模型驱动的智能体工作台"
    site_logo_url: str | None = None
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pigeon"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    secret_key: str | None = None
    llm_timeout_seconds: float = 60.0
    # 单轮对话允许的模型请求次数（每次工具往返算一次）；pydantic-ai 默认 50，
    # 复杂页面/多工具任务很容易撞线，这里给足余量，仍可限制失控循环
    agent_request_limit: int = Field(default=200, ge=10, le=2_000)
    # 历史上下文估算达到模型窗口的这个比例时，开跑前先压缩
    compaction_threshold: float = Field(default=DEFAULT_COMPACTION_THRESHOLD, ge=0.1, le=1.0)
    # SSE 事件队列的内存上限：超出后旧事件落到临时 jsonl，0 表示不限
    render_queue_max_backlog: int = Field(default=10_000, ge=0)
    # Redis：配置后事件队列与「每会话一个活跃 run」的互斥跨进程共享，
    # 可以多 worker 部署；留空退回进程内实现（单 worker / 本地开发）。
    redis_url: str | None = None
    # run 结束后事件流在 Redis 里的保留时长，供迟到的消费者回放
    render_retain_seconds: int = Field(default=600, ge=60)

    # 操作日志：HTTP 请求/响应异步落库
    operation_log_enabled: bool = True
    operation_log_queue_max: int = Field(default=10_000, ge=100)
    operation_log_batch_size: int = Field(default=200, ge=1, le=1_000)
    operation_log_flush_ms: int = Field(default=500, ge=50, le=10_000)
    operation_log_max_request_body: int = Field(default=8_192, ge=0)
    operation_log_max_response_body: int = Field(default=16_384, ge=0)
    operation_log_retention_days: int = Field(default=30, ge=0)
    # 分享/签名直链的路径里直接带可用凭证，落进操作日志等于把链接抄了一份，所以排除
    operation_log_exclude_paths: str = (
        "/api/v1/health,/api/v1/ready,/api/v1/public/shares,/api/v1/files/*/link,"
        "/docs,/openapi.json,/redoc"
    )
    operation_log_trust_proxy: bool = False

    # DeepSeek Search / Fetch：没有 key 时工具不下发给模型
    deepseek_api_key: str | None = None
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_search_timeout_seconds: float = 20.0
    deepseek_fetch_timeout_seconds: float = 30.0

    # 功能开关：平台级总闸。关闭后即使凭证齐全，也不会把对应工具下发给模型；
    # 请求级开关（enable_web_search 等）在这层之上再收窄一次。
    feature_web_search_enabled: bool = True
    feature_image_generation_enabled: bool = True
    # 关闭后即使配了沙箱凭证，也不会创建云端沙箱或下发 run_command
    feature_sandbox_enabled: bool = True

    # 积分计费：关着时只统计用量不扣分，避免配好单价前把所有人挡在门外。
    # 单价单位是"每 100 万 token 多少积分"，与各家官方报价口径一致。
    billing_enabled: bool = False
    credit_default_input_per_1m: float = 2.0
    credit_default_output_per_1m: float = 8.0
    credit_default_per_image: float = 20.0

    # S3 兼容对象存储：AWS S3 / 阿里云 OSS / MinIO / RustFS 共用一套配置，
    # 只有 endpoint_url 不同。全部可选，没配 bucket 就是未启用。
    s3_endpoint_url: str | None = None
    # 浏览器直连对象存储用的地址：容器内网 endpoint 和公网域名不同时必须单独配，
    # 预签名 URL 才能被浏览器访问；留空沿用 s3_endpoint_url。
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    # 对象 key 的根前缀，多个环境共用一个桶时靠它隔开
    s3_prefix: str = "pigeon"
    # OSS 等只支持虚拟主机寻址的走 virtual；MinIO / RustFS 用 path
    s3_addressing_style: Literal["path", "virtual"] = "path"
    s3_presign_ttl_seconds: int = Field(default=600, ge=60, le=86_400)
    # 同源媒体直链的签名窗口；同一窗口内 URL 一致，浏览器缓存才命中
    file_link_ttl_seconds: int = Field(default=21_600, ge=600, le=86_400)
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
    admin_password: str = DEFAULT_ADMIN_PASSWORD

    # SMTP（发件邮箱）；没配 host 就不发验证邮件
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_tls: Literal["none", "starttls", "ssl"] = "starttls"
    # 连接与发信的最长等待。端口写错或出网被挡时，内核的 SYN 重试能一路等到 ~270 秒；
    # 注册请求正跑在这条同步链上，没有上限就等于把一次注册变成一次超时
    smtp_timeout_seconds: int = Field(default=20, ge=1, le=120)
    # 留空则用 SMTP 账号本身当发件人：多数服务商拒绝 "MAIL FROM 与授权用户不一致"
    email_from: str | None = None
    # 开了才有邮箱验证码环节；没配 SMTP 时自动当成关闭
    email_verification_required: bool = False

    @property
    def sender_address(self) -> str:
        """实际写进 From 头的地址。

        绝大多数 SMTP 服务商（阿里云、QQ、网易、腾讯云 SES…）会拒绝发件人与
        登录账号不一致的信，直接 501 "Mail from address must be same as
        authorization user"。所以没显式配置发件人、或仍停留在出厂占位地址时，
        一律回落到 SMTP 账号。
        """
        candidate = (self.email_from or "").strip()
        if candidate and _PLACEHOLDER_FROM not in candidate:
            return candidate
        if self.smtp_user:
            return self.smtp_user
        return _FALLBACK_FROM

    @property
    def is_email_verification_enabled(self) -> bool:
        return bool(self.smtp_host) and self.email_verification_required

    @property
    def can_use_web_search(self) -> bool:
        """联网搜索就绪 = 凭证齐全且平台总闸开着；能力下发一律走这里，别再各自拼。"""
        return bool(self.deepseek_api_key) and self.feature_web_search_enabled

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: list[str]) -> list[str]:
        # allow_credentials=True 与通配符组合非法，必须显式列出来源
        if "*" in value:
            raise ValueError("cors_origins 不能包含 '*'；请列出明确来源")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
