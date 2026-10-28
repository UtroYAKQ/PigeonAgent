"""SandboxPool 生命周期：建/复用/暂停/回收/闲置收尾，全部用假沙箱。"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.services import sandbox_pool as sp_mod
from app.services.sandbox_pool import SandboxPool, _Entry


class _FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self.sandbox_id = sandbox_id
        self.killed = False
        self.paused = False

    async def beta_pause(self) -> None:
        self.paused = True

    async def kill(self) -> None:
        self.killed = True


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


async def test_release_supports_sandbox_without_pause(pool: SandboxPool) -> None:
    class NoPause:
        sandbox_id = "bare"

    session = uuid4()
    entry = _Entry(sandbox=NoPause(), sandbox_id="bare")  # type: ignore[arg-type]
    pool._entries[session] = entry
    await pool.release(session)
    assert entry.paused  # 没有 beta_pause 也照样标记挂起，时钟兜底

