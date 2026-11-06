# 配置

配置分两层：

1. **进程配置**：只从环境变量 / `.env` 读取，修改后需要重启进程。包括数据库、`SECRET_KEY`、Redis、S3、默认管理员、CORS 等。
2. **运行时配置**：存在 `app_configs` 表，管理员可以在后台修改，下一轮请求或 run 生效。优先级是 **数据库 > 环境变量 > 代码默认**。

`.env.example` 是进程配置的完整清单和注释；本文只列容易踩坑的部分。

## 必填项

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | Fernet key。缺失或仍为旧示例值时应用拒绝启动。用于 API key 加密、分享链接、邮箱验证码 HMAC。 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 首次启动且库中没有用户时创建管理员。密码不要保留 `change-me` / `admin123456`。 |
| `DATABASE_URL` | PostgreSQL，例如 `postgresql+asyncpg://user:pass@host:5432/pigeon`。Docker Compose 里主机名用 `postgres`。 |

生成 `SECRET_KEY`：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> 更换 `SECRET_KEY` 会让已加密的模型 API key、SMTP 密码、沙箱 key、分享链接和未使用的邮箱验证码失效。轮换前先导出需要重新录入的配置。

## Redis

不配 `REDIS_URL` 时使用进程内队列和进程内 run 租约，只支持单 worker。配置后：

- SSE 事件流由 Redis Streams 承载，迟到的标签页可以回放。
- 「每会话一个活跃 run」的互斥跨进程共享，可以启动多个 uvicorn worker。
- **跨 worker 取消**：run 的归属键、取消标记和取消 Pub/Sub 放进 Redis；取消请求落到任意 worker 都能送达持有该 run 的进程，listener 重连后会补查取消标记。
- **跨 worker 沙箱复用**：`SandboxPool` 把远端沙箱指针写进 Redis，下一轮 run 漂到另一个 worker 时会 connect 同一个沙箱，工作区文件不会丢；如果检测到另一个 worker 仍在用该沙箱，会新建隔离沙箱而不是共享容器。
- `RENDER_RETAIN_SECONDS` 控制 run 结束后事件在 Redis 里的保留时间。

多 worker 时所有进程必须连接同一个 Redis 和同一个 PostgreSQL；`SECRET_KEY` 也必须一致，否则加密配置、分享链接和验证码摘要会互相读不出来。

## 对象存储

不配 `S3_BUCKET` 时文件能力关闭。配置后支持 AWS S3、阿里云 OSS、MinIO、RustFS 等 S3 兼容服务。

| 变量 | 说明 |
| --- | --- |
| `S3_ENDPOINT_URL` | 后端访问地址。Compose 里填 `http://rustfs:9000`；OSS 填地域 endpoint。 |
| `S3_PUBLIC_ENDPOINT_URL` | 浏览器访问地址。媒体直链和上传签名都使用该地址；HTTPS 站点必须填 HTTPS，否则图片会被混合内容拦截。 |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | 访问凭证。 |
| `S3_ADDRESSING_STYLE` | MinIO / RustFS 用 `path`，OSS 用 `virtual`。 |
| `S3_PREFIX` | 对象 key 根前缀。 |
| `FILE_LINK_TTL_SECONDS` | 媒体直链签名窗口；同一窗口内 URL 一致，浏览器缓存才命中。 |

如果使用浏览器直传（presign PUT），需要在桶上配置 CORS，允许站点 origin 的 `PUT` / `GET`。

## 运行时配置

管理后台「平台配置」里可以维护以下分组（密钥类值只显示是否已配置）：

| 分组 | 主要内容 |
| --- | --- |
| 站点 | 站点名称、简介、Logo；公开接口 `/api/v1/configs/public` 下发。 |
| 功能开关 | 联网搜索、图片生成、沙箱的全局开关。 |
| 联网搜索 | DeepSeek Search & Fetch 的 key、base URL、超时。 |
| 沙箱 | e2b 兼容服务的 key、API URL、domain、template、空闲回收时间、本地工作区根目录。 |
| 邮箱 | SMTP host/port/user/password/TLS、发件人、是否强制邮箱验证。 |
| 文件 | 单文件上传上限。 |
| 日志 | 操作日志开关、队列、批量、请求/响应体上限、排除路径、保留天数、是否信任代理头。 |
| 用量与积分 | 是否启用计费、默认输入/输出/图片单价。 |

配置类接口：

- `GET /api/v1/configs`：管理员查看全部配置、当前值和来源（`database` / `environment` / `default`）。
- `PATCH /api/v1/configs/{key}`：管理员修改，body 为 `{"value": "..."}`；传 `{"value": null}` 撤销数据库覆盖。
- `GET /api/v1/configs/public`：免登录读取站点名称、简介、Logo 和能力开关。

启动时会把环境变量里显式配置、但数据库里还没有值的配置项补进 `app_configs`；数据库已有值时以数据库为准。

## 模型

对话模型在「管理后台 → 模型管理」维护，字段包括：

- 供应商、API base、模型名、API key（加密存储）。
- 思考挡位：只有勾选的挡位才会出现在输入框旁的选择器里；后端映射为 Pydantic AI 的 `ModelSettings.thinking`。
- 上下文窗口：用于判断何时触发上下文压缩；留空表示不压缩。
- 是否支持工具调用：关闭后不会收到浏览器工具、联网搜索或文件工作区。
- 价格：用于按 token 计费；未启用计费时只统计用量。

图片模型单独维护（`image_models`），走 LiteLLM 的 `image_generation`。输入框的图片选择框只会列出启用模型；再点一次当前模型即取消。各家网关的地址、常用尺寸和模型名示例在后台有预设，最终请求 URL 会在表单里直接显示。

## 邮箱验证

- 不配 `SMTP_HOST` 时不发邮件，`EMAIL_VERIFICATION_REQUIRED` 自动视为关闭。
- 开启后注册需要验证码；未验证账号再次注册时，即使关闭邮箱验证也必须提供正确密码才能激活。
- 发件人留空时使用 SMTP 账号本身，避免服务商拒绝 `MAIL FROM` 与授权用户不一致。

## 操作日志

所有 HTTP 操作默认异步写入 `operation_logs`，管理员写操作以 `kind='admin'` 记在同一张表。请求只做有界拷贝和入队，队列满时丢弃并告警，不阻塞业务。文件、二进制和 SSE 不保存 body；密码、token、Cookie、API key 递归脱敏。

采集开关、队列大小、批量、体积上限、排除路径和保留期都可以在后台修改，立即生效。
