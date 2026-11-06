"""跨 worker 的 run 取消总线：归属键 + Pub/Sub 广播。"""

import asyncio
from uuid import uuid4

import pytest
from fakeredis import FakeAsyncRedis
from pydantic_ai import CancellationToken

from app.core.exceptions import NotFoundError
from app.services.run import RunRegistry
from app.services.run_control import RunControl


def build_registry(client: FakeAsyncRedis, prefix: str) -> RunRegistry:
    return RunRegistry(control=RunControl(client, key_prefix=prefix))


async def wait_cancelled(token: CancellationToken) -> None:
    for _ in range(100):
        if token.cancelled:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("取消信号没有跨 worker 送达")


async def test_cancel_reaches_the_worker_that_owns_the_run() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    owner = build_registry(client, prefix)
    other = build_registry(client, prefix)
    await owner.start()
    await other.start()
    await owner.wait_ready()
    await other.wait_ready()

    session_id = uuid4()
    token = CancellationToken()
    await owner.register("run-1", session_id, token)

    await other.cancel_run(session_id, "run-1")
    await wait_cancelled(token)

    await owner.aclose()
    await other.aclose()


async def test_cancel_unknown_run_is_not_found() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    registry = build_registry(client, prefix)
    await registry.start()
    try:
        with pytest.raises(NotFoundError):
            await registry.cancel_run(uuid4(), "missing-run")
    finally:
        await registry.aclose()


async def test_owner_key_isolated_by_session() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    owner = build_registry(client, prefix)
    other = build_registry(client, prefix)
    await owner.start()
    await other.start()
    await owner.wait_ready()
    await other.wait_ready()

    session_id = uuid4()
    token = CancellationToken()
    await owner.register("run-2", session_id, token)

    with pytest.raises(NotFoundError):
        await other.cancel_run(uuid4(), "run-2")
    assert not token.cancelled

    await owner.aclose()
    await other.aclose()


async def test_unregister_removes_owner_key() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    registry = build_registry(client, prefix)
    session_id = uuid4()
    await registry.register("run-3", session_id, CancellationToken())
    owner_key = f"{prefix}:run-control:owner:run-3"
    cancel_key = f"{prefix}:run-control:cancel:run-3"
    assert await client.get(owner_key) == str(session_id).encode()

    await client.set(cancel_key, "1")
    await registry.unregister("run-3")
    assert await client.get(owner_key) is None
    assert await client.get(cancel_key) is None
    await registry.aclose()


async def test_cancel_flag_reconciles_messages_lost_while_listener_was_down() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    registry = build_registry(client, prefix)
    await registry.start()
    await registry.wait_ready()

    session_id = uuid4()
    token = CancellationToken()
    await registry.register("run-lost", session_id, token)
    # 模拟 listener 断线期间收到取消：只有 durable 标记，没有 Pub/Sub 消息
    await client.set(f"{prefix}:run-control:cancel:run-lost", "1")

    await registry._reconcile_cancels()
    assert token.cancelled
    await registry.aclose()


async def test_register_honors_cancel_flag_that_arrived_early() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    registry = build_registry(client, prefix)
    await registry.start()
    await registry.wait_ready()

    session_id = uuid4()
    await client.set(f"{prefix}:run-control:cancel:run-early", "1")
    token = CancellationToken()
    await registry.register("run-early", session_id, token)
    assert token.cancelled
    await registry.aclose()


async def test_touch_restores_owner_key_after_redis_restart() -> None:
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    registry = build_registry(client, prefix)
    session_id = uuid4()
    await registry.register("run-restore", session_id, CancellationToken())
    owner_key = f"{prefix}:run-control:owner:run-restore"
    await client.delete(owner_key)

    await registry.touch("run-restore")
    assert await client.get(owner_key) == str(session_id).encode()
    await registry.aclose()


async def test_local_registry_still_cancels_without_redis() -> None:
    registry = RunRegistry()
    token = CancellationToken()
    session_id = uuid4()
    await registry.register("run-local", session_id, token)
    await registry.cancel_run(session_id, "run-local")
    assert token.cancelled
    await registry.aclose()
