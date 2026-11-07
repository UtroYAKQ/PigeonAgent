"""应用配置项的代码侧规格：类型、分组和默认展示信息。"""

from __future__ import annotations

from dataclasses import dataclass

from app.enums.config import ConfigCategory, ConfigValueType


@dataclass(frozen=True, slots=True)
class ConfigSpec:
    key: str
    category: ConfigCategory
    label: str
    description: str
    value_type: ConfigValueType
    # 可选的枚举值（如 smtp_tls）；为空表示不限制
    choices: tuple[str, ...] | None = None

    @property
    def is_secret(self) -> bool:
        return self.value_type is ConfigValueType.SECRET


CONFIG_SPECS: tuple[ConfigSpec, ...] = (
    # ------------------------------------------------------------------ 站点
    ConfigSpec(
        key="site_name",
        category=ConfigCategory.SITE,
        label="站点名称",
        description="浏览器标题、登录页等位置展示的名称",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="site_description",
        category=ConfigCategory.SITE,
        label="站点简介",
        description="公开接口下发的站点描述，可用于登录页或欢迎语",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="site_logo_url",
        category=ConfigCategory.SITE,
        label="站点 Logo",
        description="Logo 图片地址；留空使用前端内置品牌标识",
        value_type=ConfigValueType.STRING,
    ),
    # --------------------------------------------------------------- DeepSeek
    ConfigSpec(
        key="deepseek_api_key",
        category=ConfigCategory.DEEPSEEK,
        label="DeepSeek API Key",
        description="联网搜索与网页抓取凭证；未配置时前端搜索开关不可用",
        value_type=ConfigValueType.SECRET,
    ),
    ConfigSpec(
        key="deepseek_api_base",
        category=ConfigCategory.DEEPSEEK,
        label="DeepSeek API 地址",
        description="Search / Fetch 服务地址，默认 https://api.deepseek.com",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="deepseek_search_timeout_seconds",
        category=ConfigCategory.DEEPSEEK,
        label="搜索超时（秒）",
        description="单次网页搜索请求的超时时间",
        value_type=ConfigValueType.FLOAT,
    ),
    ConfigSpec(
        key="deepseek_fetch_timeout_seconds",
        category=ConfigCategory.DEEPSEEK,
        label="抓取超时（秒）",
        description="单次网页正文抓取请求的超时时间",
        value_type=ConfigValueType.FLOAT,
    ),
    # ------------------------------------------------------------------ e2b
    ConfigSpec(
        key="sandbox_api_key",
        category=ConfigCategory.SANDBOX,
        label="沙箱 API Key",
        description="e2b 兼容沙箱凭证；留空则使用本地临时工作区",
        value_type=ConfigValueType.SECRET,
    ),
    ConfigSpec(
        key="sandbox_api_url",
        category=ConfigCategory.SANDBOX,
        label="沙箱 API 地址",
        description="例如 https://api.cn-hangzhou.e2b.fc.aliyuncs.com",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="sandbox_domain",
        category=ConfigCategory.SANDBOX,
        label="沙箱域名后缀",
        description="沙箱实例的域名后缀，例如 cn-hangzhou.e2b.fc.aliyuncs.com",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="sandbox_template",
        category=ConfigCategory.SANDBOX,
        label="沙箱模板",
        description="创建沙箱使用的模板 ID",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="sandbox_idle_seconds",
        category=ConfigCategory.SANDBOX,
        label="沙箱空闲回收（秒）",
        description="无工具活动多久后回收沙箱，最小 60 秒",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="sandbox_pause_seconds",
        category=ConfigCategory.SANDBOX,
        label="沙箱挂起等待（秒）",
        description="最后一轮结束后空闲多久挂起沙箱以停止计费；0 表示下一次巡检立即挂起",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="workspace_root",
        category=ConfigCategory.SANDBOX,
        label="本地工作区根目录",
        description="本地模式的临时工作区根目录；留空使用系统临时目录",
        value_type=ConfigValueType.STRING,
    ),
    # ------------------------------------------------------------------ 邮箱
    ConfigSpec(
        key="smtp_host",
        category=ConfigCategory.EMAIL,
        label="SMTP 主机",
        description="邮件服务器地址；留空则不发验证邮件",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="smtp_port",
        category=ConfigCategory.EMAIL,
        label="SMTP 端口",
        description="常见为 587（STARTTLS）或 465（SSL）",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="smtp_user",
        category=ConfigCategory.EMAIL,
        label="SMTP 用户名",
        description="登录邮件服务器的账号",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="smtp_password",
        category=ConfigCategory.EMAIL,
        label="SMTP 密码",
        description="登录邮件服务器的密码或授权码",
        value_type=ConfigValueType.SECRET,
    ),
    ConfigSpec(
        key="smtp_tls",
        category=ConfigCategory.EMAIL,
        label="SMTP 加密方式",
        description="none / starttls / ssl",
        value_type=ConfigValueType.STRING,
        choices=("none", "starttls", "ssl"),
    ),
    ConfigSpec(
        key="smtp_timeout_seconds",
        category=ConfigCategory.EMAIL,
        label="SMTP 超时秒数",
        description="连接与发信的最长等待；端口或出网出问题时，注册最多等这么久",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="email_from",
        category=ConfigCategory.EMAIL,
        label="发件人",
        description="验证码邮件的 From 头；留空则用 SMTP 用户名（服务商通常要求两者一致）",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="email_verification_required",
        category=ConfigCategory.EMAIL,
        label="注册需要邮箱验证",
        description="开启且配置了 SMTP 时，注册需先输入邮箱验证码",
        value_type=ConfigValueType.BOOLEAN,
    ),
    # ------------------------------------------------------------------ 文件
    ConfigSpec(
        key="max_upload_bytes",
        category=ConfigCategory.FILES,
        label="单文件大小上限（字节）",
        description="服务端直传和预签名上传共用的上限，默认 20 MB",
        value_type=ConfigValueType.INTEGER,
    ),
    # ------------------------------------------------------------------ 日志
    ConfigSpec(
        key="operation_log_enabled",
        category=ConfigCategory.LOGGING,
        label="启用操作日志",
        description="记录所有 HTTP 操作的请求参数与返回结果",
        value_type=ConfigValueType.BOOLEAN,
    ),
    ConfigSpec(
        key="operation_log_trust_proxy",
        category=ConfigCategory.LOGGING,
        label="信任代理头",
        description="开启后从 X-Forwarded-For 读取客户端 IP；仅在可信反代后开启",
        value_type=ConfigValueType.BOOLEAN,
    ),
    ConfigSpec(
        key="operation_log_exclude_paths",
        category=ConfigCategory.LOGGING,
        label="排除路径",
        description="逗号分隔的路径前缀，例如 /api/v1/health,/docs",
        value_type=ConfigValueType.STRING,
    ),
    ConfigSpec(
        key="operation_log_queue_max",
        category=ConfigCategory.LOGGING,
        label="队列上限",
        description="异步日志队列最多缓存多少条；队列长度调整在下次启动生效，满了会丢弃并计数",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="operation_log_batch_size",
        category=ConfigCategory.LOGGING,
        label="批量写入条数",
        description="单个事务最多写入多少条日志",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="operation_log_flush_ms",
        category=ConfigCategory.LOGGING,
        label="批量写入间隔（毫秒）",
        description="队列未满时最多等待多久再落库",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="operation_log_max_request_body",
        category=ConfigCategory.LOGGING,
        label="请求体上限（字节）",
        description="超过后记录截断标记，不保存完整请求体",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="operation_log_max_response_body",
        category=ConfigCategory.LOGGING,
        label="响应体上限（字节）",
        description="超过后记录截断标记，不保存完整响应体",
        value_type=ConfigValueType.INTEGER,
    ),
    ConfigSpec(
        key="operation_log_retention_days",
        category=ConfigCategory.LOGGING,
        label="日志保留天数",
        description="0 表示永久保留；后台每小时分批清理过期日志",
        value_type=ConfigValueType.INTEGER,
    ),
    # ------------------------------------------------------------- 功能开关
    ConfigSpec(
        key="feature_web_search_enabled",
        category=ConfigCategory.FEATURES,
        label="允许联网搜索",
        description="关闭后即使已配置 DeepSeek 凭证，模型也不会收到搜索工具",
        value_type=ConfigValueType.BOOLEAN,
    ),
    ConfigSpec(
        key="feature_image_generation_enabled",
        category=ConfigCategory.FEATURES,
        label="允许图片生成",
        description="关闭后即使已配置图片模型，助手也不会获得出图能力",
        value_type=ConfigValueType.BOOLEAN,
    ),
    ConfigSpec(
        key="feature_sandbox_enabled",
        category=ConfigCategory.FEATURES,
        label="允许沙箱执行",
        description="关闭后即使已配置沙箱凭证，也不会创建云端沙箱或下发命令执行工具",
        value_type=ConfigValueType.BOOLEAN,
    ),
    # ------------------------------------------------------------------ 积分
    ConfigSpec(
        key="billing_enabled",
        category=ConfigCategory.FEATURES,
        label="启用积分计费",
        description="关闭时按 token 用量照常统计，但不扣分、不拦截；首次上线建议先配好单价再开",
        value_type=ConfigValueType.BOOLEAN,
    ),
    ConfigSpec(
        key="credit_default_input_per_1m",
        category=ConfigCategory.BILLING,
        label="默认输入单价",
        description="模型没单独配时用它：每 100 万输入 token 扣多少积分",
        value_type=ConfigValueType.FLOAT,
    ),
    ConfigSpec(
        key="credit_default_output_per_1m",
        category=ConfigCategory.BILLING,
        label="默认输出单价",
        description="模型没单独配时用它：每 100 万输出 token 扣多少积分",
        value_type=ConfigValueType.FLOAT,
    ),
    ConfigSpec(
        key="credit_default_per_image",
        category=ConfigCategory.BILLING,
        label="默认出图单价",
        description="图片模型没单独配时用它：每生成一张图扣多少积分",
        value_type=ConfigValueType.FLOAT,
    ),
)

SPEC_BY_KEY: dict[str, ConfigSpec] = {spec.key: spec for spec in CONFIG_SPECS}

CATEGORY_LABELS: dict[ConfigCategory, str] = {
    ConfigCategory.SITE: "站点",
    ConfigCategory.DEEPSEEK: "联网搜索",
    ConfigCategory.SANDBOX: "沙箱",
    ConfigCategory.EMAIL: "邮箱",
    ConfigCategory.FILES: "文件",
    ConfigCategory.LOGGING: "日志",
    ConfigCategory.FEATURES: "功能开关",
    ConfigCategory.BILLING: "积分",
}
