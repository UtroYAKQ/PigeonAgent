import os
import uuid as uuid_mod
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet

# app.main 在 import 时就会构造并缓存 Settings；SECRET_KEY 缺失会直接拒绝启动，
# 所以测试身份用的 key 必须在 import 之前落好。
TEST_SECRET_KEY = Fernet.generate_key().decode()
os.environ["SECRET_KEY"] = TEST_SECRET_KEY
os.environ["ADMIN_PASSWORD"] = "pigeon-test-admin-password"

# 测试不连真实沙箱：环境变量盖过 .env 里的 SANDBOX_API_KEY，全部走本地工作区。
# 必须在任何 app 模块 import 之前设置——app.main 在 import 时就会构造并缓存 Settings。
os.environ["SANDBOX_API_KEY"] = ""
# 同理：.env 里可能配了真实的联网搜索 key，会让「未配置时能力应关闭」的断言失效。
# 需要测「已配置」的用例统一通过 PATCH /configs 写入数据库覆盖。
os.environ["DEEPSEEK_API_KEY"] = ""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import security
from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter
from app.db import Base, enable_sqlite_pragmas, get_db, get_session_factory
from app.main import app
from app.models.user import User
from app.render import RenderHub
from app.services.run.registry import RunRegistry
from app.tasks.operation_log import OperationLogger

# 默认临时文件 SQLite；设 TEST_DATABASE_URL 可让整套测试跑在 PostgreSQL 上
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")

# 所有测试共用一个固定身份：HTTP 端点和服务层共用的 owner（hash 只算一次）
TEST_USER_ID = uuid_mod.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_EMAIL = "pigeon-test@example.com"
_TEST_USER_HASH = security.hash_password("pigeon-password")


def issue_access_token() -> str:
    return security.issue_token(
        str(TEST_USER_ID),
        security.ACCESS,
        secret_key=TEST_SECRET_KEY,
        expires_in=timedelta(hours=2),
    )


async def ensure_test_user(db_session: AsyncSession) -> User:
    # 默认身份是管理员：模型属于全局资源，配置类用例都靠这个身份
    user = User(
        id=TEST_USER_ID,
        email=TEST_USER_EMAIL,
        password_hash=_TEST_USER_HASH,
        display_name="测试用户",
        is_admin=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
def test_user_id() -> uuid_mod.UUID:
    return TEST_USER_ID


@pytest.fixture(autouse=True)
def _clear_media_cache() -> Iterator[None]:
    # 媒体缓存是进程级单例；每个用例前后清空，避免用例之间互相命中
    from app.services import file_service

    file_service.clear_media_cache()
    yield
    file_service.clear_media_cache()


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    url = TEST_DATABASE_URL
    if url.startswith("sqlite"):
        # StaticPool 会把同一个连接分给并发写入的多个 session：一方 rollback 会吞掉
        # 另一方还没提交的 INSERT。agent run 和事件消费确实会同时写库，所以 SQLite
        # 也用临时文件库（NullPool：每次 checkout 一个独立连接，和 Postgres 行为一致）。
        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(url)
    enable_sqlite_pragmas(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    return async_sessionmaker(bind, expire_on_commit=False)


@pytest.fixture
async def client(
    db_session: AsyncSession, db_session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    def override_get_settings() -> Settings:
        # 测试里关掉沙箱和对象存储：默认全走本地工具 + 本地工作区；
        # _env_file=None 避免仓库根目录的 .env 把真实密钥带进测试库。
        return Settings(_env_file=None, secret_key=TEST_SECRET_KEY, sandbox_api_key=None)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory
    app.state.render_hub = RenderHub()
    app.state.run_registry = RunRegistry()
    # app 是模块级单例：限流计数每个用例清空，否则前面的用例会把后面的登录请求挡住
    app.state.rate_limiter = RateLimiter()
    operation_logger = OperationLogger(
        db_session_factory,
        Settings(_env_file=None, secret_key=TEST_SECRET_KEY, sandbox_api_key=None),
    )
    operation_logger.start()
    app.state.operation_logger = operation_logger
    # 默认登录为固定测试用户；需要别的身份（新人/陌生人）的测试自己带 token 覆盖
    await ensure_test_user(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        http_client.headers["Authorization"] = f"Bearer {issue_access_token()}"
        yield http_client
    await operation_logger.aclose()
    await app.state.run_registry.cancel_all()
    app.dependency_overrides.clear()
