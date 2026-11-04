# 贡献指南

感谢愿意花时间改进 PigeonAgent。下面是本地开发、提交和验收的最小路径。

## 环境

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- Docker（可选，用于 PostgreSQL / Redis / RustFS）
- Windows 用户可以使用仓库里的 `.cmd` 脚本；其他平台按下面命令手动启动。

## 后端

```bash
uv sync --extra dev
cp .env.example .env
# 至少设置 SECRET_KEY、ADMIN_PASSWORD、DATABASE_URL
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

没有 PostgreSQL 时，可以先跑 mock 环境（SQLite + 进程内 S3 + 假模型）：

```bash
uv run python scripts/mock_server.py
```

## 前端

```bash
cd frontend
npm ci
npm run dev
```

Vite 默认把 `/api` 代理到 `127.0.0.1:8000`。mock 模式：

```bash
npm run dev -- --mode mock
```

## 质量门禁

提交前请确保以下命令全部通过：

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

- 后端 `mypy` 对 `app/` 严格检查，`tests/` 暂时通过 overrides 不阻断。
- 前端使用 ESLint + Vitest；`npm run build` 同时跑 `vue-tsc`。
- CI 会额外跑一遍 PostgreSQL 测试。

## 提交

- 使用 Conventional Commits：`feat: ...`、`fix: ...`、`docs: ...`、`refactor: ...`、`test: ...`、`chore: ...`。
- 一个提交只做一件事；重构和行为变更尽量分开，方便 review 和回滚。
- 提交前检查 `git diff`，不要提交 `.env`、`.mock/`、`.workbuddy/`、`.backup/`、数据库文件或任何真实密钥。
- 新增/修改数据库模型时：

```bash
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
```

## Pull Request

请在 PR 描述里写清楚：

1. 改了什么、为什么改。
2. 对用户可见的行为变化。
3. 如何验证（命令、页面、截图或测试）。
4. 是否涉及数据库迁移、配置变更或安全边界。

CI 通过、测试覆盖到改动路径、没有新增未使用代码或无关重构，才会进入合并。

## 安全

不要公开披露未修复的漏洞。报告方式见 [SECURITY.md](SECURITY.md)。如果发现仓库里误提交了密钥，请立即提醒维护者轮换，而不是只提一个删除文件的 PR。

## 文档

- 用户文档在 `README.md` 和 `docs/`。
- 前端细节在 `frontend/README.md`。
- 评测用例说明在 `evals/README.md`。
- 代码注释使用中文，保持简短；解释“为什么”而不是复述“做了什么”。
