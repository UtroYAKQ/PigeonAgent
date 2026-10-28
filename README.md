# PigeonAgent

基于 FastAPI 的后端服务，按 API / schema / service / model 分层，适合中型项目扩展。

## 目录结构

```text
app/
├── api/                  # 路由、版本分组、依赖注入
│   ├── v1/endpoints/     # 按资源拆分的端点
│   ├── deps.py           # 公共依赖（如数据库会话）
│   └── router.py
├── core/                 # 配置等基础设施
├── db/                   # 引擎、会话、Declarative Base
├── models/               # SQLAlchemy ORM 模型
├── schemas/              # Pydantic 请求/响应模型
├── services/             # 业务逻辑
└── main.py               # 应用入口
migrations/               # Alembic 迁移
tests/                    # pytest 测试
```

## 启动

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

也可以使用 venv + pip：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

文档地址：http://127.0.0.1:8000/docs

## 质量检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## 数据库

默认使用 PostgreSQL。先在 `.env` 里配置 `DATABASE_URL`，再执行迁移：

```bash
uv run alembic upgrade head
```

pytest 默认给每个用例开一个临时文件 SQLite，不需要数据库服务；想让整套测试跑在 PostgreSQL 上就设 `TEST_DATABASE_URL`：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/pigeon_test uv run pytest
```

用文件库而不是内存库（StaticPool）是因为 agent run 和事件消费会并发写库，共用一条连接时一方的 rollback 会吞掉另一方还没提交的写入。

```bash
# DATABASE_URL=sqlite+aiosqlite:///./pigeon.db
```

新增或修改模型后生成迁移：

```bash
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
```
