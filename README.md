<p align="center">
  <img src="frontend/public/logo.png" width="72" alt="PigeonAgent" />
</p>

<h1 align="center">PigeonAgent</h1>

<p align="center">
  可自托管的大模型智能体工作台：流式对话、工具编排、审批卡片、文件工作区与平台运营后台。
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="docs/architecture.md">架构</a> ·
  <a href="docs/configuration.md">配置</a> ·
  <a href="docs/operations.md">运维</a> ·
  <a href="CONTRIBUTING.md">贡献</a>
</p>

<p align="center">
  <img src="docs/assets/demo.gif" alt="PigeonAgent 演示：提问、流式回复、HTML 预览与代码预览" width="600" />
</p>

<p align="center">
  <sub>演示：提问 → 流式回复 → HTML 预览 → 代码预览；<a href="docs/assets/demo.webm">观看完整视频（WebM，约 14 秒）</a></sub>
</p>

## 功能

- **流式对话**：文本、思维链、工具调用步骤和用量通过 AG-UI 事件实时推送；刷新或重连后可以接回进行中的 run。
- **人机协作卡片**：后端审批、外部结果补填、提问卡片；同一批卡片一次只展示一张，回答完自动续跑。
- **对话树**：重新生成、编辑提问、版本切换；分支之间互不覆盖，用量按实际消耗累计。
- **文件与媒体**：图片、视频、文档上传；对象存储直链由服务端签名，浏览器直接取字节；HTML 预览在右侧独立面板打开。
- **模型管理**：对话模型与图片模型分开维护；按模型配置思考挡位、上下文窗口和工具能力；输入框可直接切换图片模型。
- **平台能力**：用户与会话管理、操作日志、积分与用量、分享链接、邮箱验证、Redis 多 worker（事件流、跨 worker 取消、沙箱复用）、S3 兼容存储（RustFS / MinIO / OSS / AWS S3）。
- **Agent 能力**：联网搜索、e2b 兼容沙箱、本地文件工作区、上下文自动压缩、提示词评测工具。
- **可观测性**：`/health`、`/ready`、请求 ID、异步操作日志、管理员审计日志。

## 界面

| 对话与 Markdown | 用量与热力图 |
| --- | --- |
| ![对话](docs/assets/chat-long.png) | ![用量](docs/assets/usage.png) |

| 模型管理 | 初始工作台 |
| --- | --- |
| ![模型管理](docs/assets/models.png) | ![初始页](docs/assets/chat-home.png) |

> 截图来自仓库自带的 mock 环境（SQLite + 进程内 S3 + 假模型），不包含任何真实账号或密钥。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI、Pydantic AI、SQLAlchemy 2 async、Alembic、PostgreSQL |
| 实时链路 | AG-UI 事件、SSE、Redis Streams（可选多 worker） |
| 存储 | S3 协议对象存储，本地 mock 使用 moto |
| Agent | Pydantic AI tools、DeepSeek Search & Fetch、e2b 兼容沙箱 |
| 图片生成 | LiteLLM `image_generation`，兼容 OpenAI / 火山方舟 / 智谱 / 硅基流动等 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Tailwind CSS v4、shadcn-vue |
| 渲染 | markstream-vue + Shiki，KaTeX / Mermaid |

## 快速开始

### Docker Compose（推荐）

需要 Docker 与 Docker Compose。先复制环境文件：

```bash
cp .env.example .env
```

至少填写下面这些值（`SECRET_KEY` 用命令生成）：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```dotenv
# .env
SECRET_KEY=<上一步生成的 Fernet key>
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<改成强密码>

POSTGRES_PASSWORD=change-me
DATABASE_URL=postgresql+asyncpg://pigeon:change-me@postgres:5432/pigeon

REDIS_URL=redis://redis:6379/0

S3_ACCESS_KEY=change-me
S3_SECRET_KEY=change-me
S3_BUCKET=pigeon-files
S3_PREFIX=pigeon
S3_ENDPOINT_URL=http://rustfs:9000
S3_PUBLIC_ENDPOINT_URL=http://localhost:9000
```

> `POSTGRES_PASSWORD` 与 `DATABASE_URL` 里的密码要保持一致。S3 的 `S3_ENDPOINT_URL` 给后端容器用服务名 `rustfs`；`S3_PUBLIC_ENDPOINT_URL` 是浏览器访问对象存储的地址。

启动：

```bash
docker compose up -d --build
```

打开 <http://localhost:8080>，用 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 登录。后端接口文档在 <http://127.0.0.1:8000/docs>。

默认端口可以通过 `FRONTEND_PORT` 修改。前端容器里的 nginx 会把 `/api` 反代到 backend，SSE 已关闭缓冲。

### 本地开发

后端：

```bash
uv sync --extra dev
cp .env.example .env          # 填 SECRET_KEY、ADMIN_PASSWORD、DATABASE_URL
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>。Vite 会把 `/api` 代理到 `127.0.0.1:8000`。

### 不接外部服务的 mock 模式

Windows 可以直接双击或执行：

```bat
scripts\dev-mock.cmd
```

其他平台手动起两个进程：

```bash
uv run python scripts/mock_server.py
cd frontend && npm run dev -- --mode mock
```

mock 使用 SQLite、进程内 moto S3 和假模型，不连 PostgreSQL / 外部对象存储。固定账号：

```text
admin@example.com / admin12345
```

> mock 账号只存在于本地 `.mock/pigeon_mock.db`，与真实部署无关。

## 配置

- 环境变量清单与注释见 [.env.example](.env.example)。
- 配置优先级：**数据库 `app_configs` > 环境变量 > 代码默认**。管理员可以在后台修改站点信息、搜索、沙箱、邮箱、文件上传、操作日志等配置；密钥类配置用 `SECRET_KEY` 加密入库，接口只返回“是否已配置”。
- 模型、图片模型、思考挡位在「管理后台 → 模型管理 / 图片模型」维护。
- 更多配置说明见 [docs/configuration.md](docs/configuration.md)。

## 项目结构

```text
app/
├── api/              # 路由与依赖注入
├── core/             # 配置、安全、异常、日志契约
├── db/               # 引擎、会话、Base
├── models/           # SQLAlchemy ORM
├── schemas/          # Pydantic 请求 / 响应
├── services/         # 业务逻辑（run、会话、用量、配置、文件…）
├── agents/           # Agent 定义、turn 编排与工具
├── domain/           # run item 等领域类型
├── render/           # SSE / Redis render hub
├── infra/            # 模型、图片、存储适配
├── sandbox/          # 沙箱与本地工作区
├── tasks/            # 操作日志、对象 GC 等后台任务
└── main.py           # 应用入口

frontend/src/         # Vue 客户端（详见 frontend/README.md）
migrations/           # Alembic 迁移
evals/                # 提示词回归工具
tests/                # pytest
deploy/               # 容器与通用 nginx 配置
```

系统边界、run 生命周期与事件流见 [docs/architecture.md](docs/architecture.md)。

## 质量检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

cd frontend
npm run lint
npm run test:unit
npm run build
```

CI 会分别跑后端（SQLite）与 PostgreSQL 两套测试，以及前端 lint、Vitest 和构建。

## 部署与运维

通用部署方式、反向代理、数据库迁移、健康检查、日志与备份见 [docs/operations.md](docs/operations.md)。仓库只包含通用的 `docker-compose.yml`、`deploy/backend.Dockerfile`、`deploy/frontend.Dockerfile` 和 `deploy/nginx.conf`，不包含任何个人服务器脚本。

## 贡献

欢迎 issue 和 pull request。开始之前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 issue 里贴密钥或生产配置。

## 讨论交流

使用、部署或开发中的问题，欢迎加入 QQ 群交流：**569594623**。

## 许可证

[MIT](LICENSE)。前端分发的第三方组件与许可证文本见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
