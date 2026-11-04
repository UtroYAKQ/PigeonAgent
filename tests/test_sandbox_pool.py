"""SandboxPool 生命周期：建/复用/暂停/回收/闲置收尾，全部用假沙箱。"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fakeredis import FakeAsyncRedis

from app.sandbox import pool as sp_mod
from app.sandbox.pool import SandboxPool, _Entry


class _FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self.sandbox_id = sandbox_id
        self.killed = False
        self.paused = False
        self.timeouts: list[int] = []

    async def beta_pause(self) -> None:
        self.paused = True

    async def set_timeout(self, seconds: Any) -> None:
        self.timeouts.append(seconds)

    async def kill(self) -> None:
        self.killed = True


class _FailingPauseSandbox(_FakeSandbox):
    """阿里云 e2b 兼容网关不支持 pause：调用即抛。"""

    async def beta_pause(self) -> None:
        raise RuntimeError("pauseSession is not enabled")


def _settings(idle: float = 600.0) -> SimpleNamespace:
    return SimpleNamespace(sandbox_idle_seconds=idle)


@pytest.fixture
def pool() -> SandboxPool:
    return SandboxPool(_settings())  # type: ignore[arg-type]


def _patch(monkeypatch: pytest.MonkeyPatch, *, created: list[Any], connect_error: bool = False):
    async def fake_create(_settings: Any) -> Any:
        if not created:
            raise AssertionError("不应再多建沙箱")
        return created.pop(0)

    async def fake_connect(_settings: Any, sandbox_id: str) -> Any:
        if connect_error:
            raise RuntimeError("sandbox is gone")
        return connect_results.pop(0)

    connect_results: list[Any] = [SimpleNamespace(sandbox_id=f"revived-{i}") for i in range(10)]
    monkeypatch.setattr(sp_mod, "create_sandbox", fake_create)
    monkeypatch.setattr(sp_mod, "connect_sandbox", fake_connect)


async def test_acquire_creates_and_reuses(
    pool: SandboxPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _FakeSandbox("sbx-1"), _FakeSandbox("sbx-2")
    _patch(monkeypatch, created=[first, second])
    session = uuid4()

    assert await pool.acquire(session, "run-1") is first
    assert await pool.acquire(session, "run-1") is first  # 同轮复用

    await pool.discard(session)
    assert first.killed

    assert await pool.acquire(session, "run-2") is second  # 下一轮新建


async def test_release_pauses_and_acquire_reconnects(
    pool: SandboxPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = _FakeSandbox("sbx-9")
    _patch(monkeypatch, created=[])  # 不允许执行中偷偷新建
    session = uuid4()
    pool._entries[session] = _Entry(sandbox=sandbox, sandbox_id="sbx-9")

    await pool.release(session)
    assert sandbox.paused and pool._entries[session].paused

    revived = SimpleNamespace(sandbox_id="sbx-9-connected")
    monkeypatch.setattr(
        sp_mod, "connect_sandbox", _fake_connect_returning(revived, expected="sbx-9")
    )
    revived_sbx = await pool.acquire(session, "run-3")
    assert revived_sbx is revived


def _fake_connect_returning(result: Any, *, expected: str) -> Any:
    async def connect(_settings: Any, sandbox_id: str) -> Any:
        assert sandbox_id == expected
        return result

    return connect


async def test_quiet_release_falls_back_to_recreate(
    pool: SandboxPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """connect 接不上 → 兜底重建新实例，编号刷新。"""
    session = uuid4()
    entry = _Entry(sandbox=_FakeSandbox("sbx-dead"), sandbox_id="sbx-dead", paused=True)
    pool._entries[session] = entry
    fresh = _FakeSandbox("sbx-new")

    async def fake_connect(_settings: Any, _sandbox_id: str) -> Any:
        raise RuntimeError("sandbox is gone")

    async def fake_create(_settings: Any) -> Any:
        return fresh

    monkeypatch.setattr(sp_mod, "connect_sandbox", fake_connect)
    monkeypatch.setattr(sp_mod, "create_sandbox", fake_create)

    sandbox = await pool.acquire(session, "run-4")
    assert sandbox is fresh
    assert pool._entries[session].paused is False


async def test_idle_sweep_kills_stale(pool: SandboxPool) -> None:
    session = uuid4()
    entry = _Entry(sandbox=_FakeSandbox("sbx-old"), sandbox_id="sbx-old")
    entry.last_touch = time.monotonic() - 10_000.0
    pool._entries[session] = entry

    recent = _Entry(sandbox=_FakeSandbox("sbx-warm"), sandbox_id="sbx-warm")
    recent.last_touch = time.monotonic()
    session2 = uuid4()
    pool._entries[session2] = recent

    cutoff = time.monotonic() - pool.settings.sandbox_idle_seconds  # type: ignore[union-attr]
    stale = [key for key, item in pool._entries.items() if item.last_touch < cutoff]
    for key in stale:
        victim = pool._entries.pop(key)
        await pool._kill_entry(victim)
    assert entry.sandbox.killed and session not in pool._entries
    assert session2 in pool._entries and not recent.sandbox.killed


async def test_aclose_kills_everything() -> None:
    pool = SandboxPool(_settings(30.0))  # type: ignore[arg-type]
    one, two = _FakeSandbox("a"), _FakeSandbox("b")
    pool._entries[uuid4()] = _Entry(sandbox=one, sandbox_id="a")
    pool._entries[uuid4()] = _Entry(sandbox=two, sandbox_id="b")
    await pool.aclose()
    assert one.killed and two.killed and not pool._entries


async def test_release_keeps_warm_when_pause_unsupported(
    pool: SandboxPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pause 用不了（或没有这个接口）就原地保活：标记必须仍是「未挂起」。

    之前不管 pause 成不成功都置 paused=True，下一轮会走「重连已暂停容器」分支；
    对不支持 pause 的网关来说，那条路等于每轮都重来一次，用户看到的就是「每轮都结束」。
    """
    sandbox = _FailingPauseSandbox("sbx-nopause")
    session = uuid4()
    entry = _Entry(sandbox=sandbox, sandbox_id="sbx-nopause")
    pool._entries[session] = entry

    await pool.release(session)
    assert entry.paused is False  # 没真挂起就不能装作挂起了

    async def fake_connect(_settings: Any, _sandbox_id: str) -> Any:
        raise AssertionError("保活中的沙箱不该走重连分支")

    monkeypatch.setattr(sp_mod, "connect_sandbox", fake_connect)
    assert await pool.acquire(session, "run-5") is sandbox


async def test_release_without_pause_api_keeps_warm(pool: SandboxPool) -> None:
    class NoPause:
        sandbox_id = "bare"

    session = uuid4()
    entry = _Entry(sandbox=NoPause(), sandbox_id="bare")  # type: ignore[arg-type]
    pool._entries[session] = entry
    await pool.release(session)
    assert entry.paused is False  # 没有 beta_pause：保活，靠空闲时钟回收


async def test_warm_acquire_renews_upstream_ttl(pool: SandboxPool) -> None:
    """上游 TTL 从创建起算：不续期的话，一直在用的沙箱到点照样被杀。"""
    sandbox = _FakeSandbox("sbx-warm")
    session = uuid4()
    pool._entries[session] = _Entry(sandbox=sandbox, sandbox_id="sbx-warm")

    assert await pool.acquire(session, "run-6") is sandbox
    assert sandbox.timeouts == [900]  # idle 600 + 300 余量，且必须是整数


async def test_paused_acquire_skips_renew(
    pool: SandboxPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已挂起的走重连分支，重连本身带 timeout，不再额外续期。"""
    revived = _FakeSandbox("sbx-resume")
    monkeypatch.setattr(
        sp_mod, "connect_sandbox", _fake_connect_returning(revived, expected="sbx-9")
    )
    session = uuid4()
    pool._entries[session] = _Entry(sandbox=_FakeSandbox("sbx-9"), sandbox_id="sbx-9", paused=True)

    assert await pool.acquire(session, "run-7") is revived
    assert revived.timeouts == []


async def test_sandbox_pointer_is_reused_across_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个 worker 共享 Redis 指针：第二个 worker 直接 connect 远端沙箱，不新建。"""
    client = FakeAsyncRedis()
    settings = _settings()
    worker_a = SandboxPool(settings, redis_client=client)  # type: ignore[arg-type]
    worker_b = SandboxPool(settings, redis_client=client)  # type: ignore[arg-type]
    shared = _FakeSandbox("sbx-shared")
    resumed = _FakeSandbox("sbx-shared")
    connects: list[str] = []

    async def fake_create(_settings: Any) -> Any:
        return shared

    async def fake_connect(_settings: Any, sandbox_id: str) -> Any:
        connects.append(sandbox_id)
        return resumed

    monkeypatch.setattr(sp_mod, "create_sandbox", fake_create)
    monkeypatch.setattr(sp_mod, "connect_sandbox", fake_connect)

    session = uuid4()
    assert await worker_a.acquire(session, "run-a") is shared
    await worker_a.release(session)
    assert shared.paused

    assert await worker_b.acquire(session, "run-b") is resumed
    assert connects == ["sbx-shared"]

    # A 的本地句柄已过时；巡检不能把 B 正在用的沙箱杀掉
    worker_a._entries[session].last_touch = time.monotonic() - 10_000.0
    await worker_a._sweep_once()
    assert not shared.killed
    assert session not in worker_a._entries

    await worker_b.discard(session)
    assert resumed.killed
    assert await client.get(f"pigeon:sandbox:{session}") is None

    await worker_a.aclose()
    await worker_b.aclose()


async def test_active_sandbox_is_not_shared_across_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """一个 worker 还在跑时，另一个 worker 即使拿到租约也新建隔离沙箱，不共享容器。"""
    client = FakeAsyncRedis()
    settings = _settings()
    worker_a = SandboxPool(settings, redis_client=client)  # type: ignore[arg-type]
    worker_b = SandboxPool(settings, redis_client=client)  # type: ignore[arg-type]
    first = _FakeSandbox("sbx-a")
    second = _FakeSandbox("sbx-b")
    created = [first, second]
    connects: list[str] = []

    async def fake_create(_settings: Any) -> Any:
        return created.pop(0)

    async def fake_connect(_settings: Any, sandbox_id: str) -> Any:
        connects.append(sandbox_id)
        raise AssertionError("活跃中的远端沙箱不应该被共享")

    monkeypatch.setattr(sp_mod, "create_sandbox", fake_create)
    monkeypatch.setattr(sp_mod, "connect_sandbox", fake_connect)

    session = uuid4()
    assert await worker_a.acquire(session, "run-a") is first
    assert await worker_b.acquire(session, "run-b") is second
    assert connects == []

    # A 收尾时远端已经指向 B 的新沙箱，A 的旧沙箱要回收
    await worker_a.release(session)
    assert first.killed
    await worker_b.discard(session)
    assert second.killed
    assert await client.get(f"pigeon:sandbox:{session}") is None

    await worker_a.aclose()
    await worker_b.aclose()
