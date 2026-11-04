# 部署与运维

仓库提供通用的容器与 nginx 配置，不包含任何个人服务器脚本。下面以 Docker Compose 为例。

## 组成

| 服务 | 作用 |
| --- | --- |
| `postgres` | 业务数据库 |
| `redis` | SSE 事件流与跨进程 run 租约（可选，但生产建议） |
| `rustfs` / `rustfs-init` | S3 兼容对象存储与桶初始化 |
| `backend` | FastAPI；启动时先执行 `alembic upgrade head`，再跑单 worker uvicorn |
| `frontend` | 多阶段构建的 Vue 静态站点；nginx 把 `/api` 反代到 backend |

## 启动

1. 准备 `.env`（至少 `SECRET_KEY`、`ADMIN_PASSWORD`、`POSTGRES_PASSWORD`、S3 凭证、`DATABASE_URL`），参考 [configuration.md](configuration.md) 和 [.env.example](../.env.example)。
2. 启动：

```bash
docker compose up -d --build
```

3. 检查：

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/ready
```

4. 打开 `http://<服务器>:${FRONTEND_PORT:-8080}`，用 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 登录。

## 反向代理与 HTTPS

`deploy/nginx.conf` 是前端容器内的配置，已经处理了 SSE 的 `proxy_buffering off` 和长连接超时。如果在外层再加一层 nginx / Caddy：

- `/api/` 必须关闭代理缓冲，并把读超时调到至少 1 小时（对话和工具可能长时间不返回）。
- `client_max_body_size` 不小于 `MAX_UPLOAD_BYTES`，默认 20 MB。
- HTTPS 站点必须让 `S3_PUBLIC_ENDPOINT_URL` 也是 HTTPS，否则图片会被浏览器按混合内容拦截。
- 如果前端与后端不同源，把前端地址加入 `CORS_ORIGINS`；同源反代则不需要。

## 数据库迁移

- 容器里的 backend 启动命令已经包含 `alembic upgrade head`。
- 本地或手动部署：

```bash
uv run alembic upgrade head
```

- 升级前先备份数据库。新增迁移后不要把旧容器直接连到新库上跑多个版本。
- 修改模型后用 `uv run alembic revision --autogenerate -m "描述"` 生成迁移，并人工检查。

## 多 worker

配置 `REDIS_URL` 后才可以启动多个 uvicorn worker；否则事件队列和活跃 run 租约只存在进程内。多 worker 时：

- 所有 worker 必须连同一个 Redis 和同一个 PostgreSQL。
- 事件保留时间 `RENDER_RETAIN_SECONDS` 要覆盖客户端断线重连的窗口。
- 后台任务（对象 GC、操作日志清理）目前按单实例设计；如果需要多实例，先确认任务不会重复执行。

## 备份

- **PostgreSQL**：定期 `pg_dump`，至少覆盖 `users`、`sessions`、`session_runs`、`app_configs`、`credit_ledgers`、`operation_logs`。
- **对象存储**：备份业务桶；数据库里的 `file_records` / `blobs` 只是引用和元数据。
- **`.env` 与 `SECRET_KEY`**：单独保管。丢失 `SECRET_KEY` 后，数据库里的加密配置无法解密，只能重新录入。

## 日志

- 应用日志输出到容器 stdout，交给 Docker / systemd / 日志采集器。
- 业务操作日志在 `operation_logs` 表，默认保留 30 天，每小时分批清理；可在后台调整。
- 每个响应带 `X-Request-ID`，应用日志和操作日志用同一个 id 串联。

## 升级

1. 备份数据库和对象存储。
2. 拉取新代码，重新构建 backend / frontend。
3. 先跑迁移，再滚动重启 backend；前端是静态资源，可以最后切换。
4. 验证 `/health`、`/ready`、登录、上传图片、发起一轮对话。

## 常见问题

| 现象 | 排查 |
| --- | --- |
| 启动直接退出，提示 `SECRET_KEY` | `.env` 没有设置，或仍是旧版示例值。按 [configuration.md](configuration.md) 生成。 |
| 登录 500 / 加密配置读不出来 | `SECRET_KEY` 换过。加密值需要重新录入，或换回原 key 后重新加密。 |
| 页面能开但接口 502 | 前端 nginx 的 `backend:8000` 解析不到后端，检查 compose 网络和服务健康状态。 |
| 图片裂开 | `S3_PUBLIC_ENDPOINT_URL` 浏览器不可达，或 HTTPS 页面指向了 HTTP 地址。 |
| 对话流式卡住 | 外层代理开启了缓冲；关闭 `/api/` 的 `proxy_buffering` 并检查超时。 |
| 数据库连不上 | 应用会以降级模式启动并输出明确的连接失败提示；确认 `DATABASE_URL` 和 PostgreSQL 健康状态后重启。 |
