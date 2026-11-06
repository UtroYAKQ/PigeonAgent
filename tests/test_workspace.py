"""工作区工具与本地工作区动作：读写、范围读、列表、收产物、安全约束。"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.bundle import build_tool_bundle
from app.agents.tools.workspace import workspace_tools
from app.core.config import Settings
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.sandbox.workspace import (
    LocalWorkspace,
    SandboxWorkspace,
    WorkspaceError,
    purge_session_workspace,
    text_read,
)
from tests.test_files import FakeStorage

LONG_TEXT = "alpha\nbeta\ngamma\ndelta\nepsilon\n"


def _local(tmp_path: Path, run_id: str = "run-1") -> LocalWorkspace:
    settings = SimpleNamespace(workspace_root=str(tmp_path))
    return LocalWorkspace(settings, FakeStorage(), uuid.uuid4(), run_id)


class _Ctx:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> Any:
        self.events.append(event)
        return event


# ------------------------------------------------------------------ text_read


def test_text_read_has_line_numbers_and_offsets() -> None:
    out = text_read(LONG_TEXT.encode(), "x.txt", offset=2, limit=2)
    assert out["lines"] == ["     2: beta", "     3: gamma"]
    assert out["total_lines"] == 5
    assert out["start_line"] == 2 and out["end_line"] == 3
    assert out["hint"] == "还有更多行"


def test_text_read_beyond_eof_and_binary_reject() -> None:
    out = text_read(LONG_TEXT.encode(), "x.txt", offset=99, limit=5)
    assert "正文只有 5 行" in out["error"]
    out = text_read(b"\x00\x01gibberish", "x.bin", offset=1, limit=5)
    assert "二进制" in out["error"]


# ------------------------------------------------------------------ LocalWorkspace


async def test_put_file_overwrites_and_read_write_roundtrip(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    first = await ws.put_file("报告.md", "内容一")
    assert first["saved_as"] == "报告.md"
    assert first["size"] == len("内容一".encode())
    second = await ws.put_file("报告.md", "内容二")
    assert second["saved_as"] == "报告.md"
    listed = await ws.list_files()
    assert {f["path"] for f in listed["entries"]} == {"报告.md"}
    text = await ws.read_file("报告.md")
    assert any("内容二" in line for line in text["lines"])
    again = await ws.read_file("不存在.md")
    assert "error" in again


def test_local_workspace_rejects_traversal(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    for evil in ("../文件.md", "/etc/passwd", "..\\.git"):
        with pytest.raises(WorkspaceError):
            ws._safe(evil)


async def test_read_file_range(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    await ws.put_file("lines.txt", LONG_TEXT)
    ranged = await ws.read_file("lines.txt", offset=2, limit=2)
    assert ranged["lines"] == ["     2: beta", "     3: gamma"]


async def test_workspace_cleanup_keeps_files_for_next_run(tmp_path: Path) -> None:
    """本轮结束不能清目录：目录是按会话分的，清了下一轮就读不到上一轮的文件。"""
    ws = _local(tmp_path)
    await ws.put_file("out.csv", "a,b\n1,2")
    await ws.cleanup()
    assert (ws.root / "out.csv").read_text(encoding="utf-8") == "a,b\n1,2"


async def test_purge_session_workspace_removes_dir(tmp_path: Path) -> None:
    settings = SimpleNamespace(workspace_root=str(tmp_path))
    session = uuid.uuid4()
    ws = LocalWorkspace(settings, FakeStorage(), session, "run-purge")
    (ws.root / "x.txt").write_text("x", encoding="utf-8")

    await purge_session_workspace(settings, session)
    assert not ws.root.exists()


async def test_publish_file_uploads_as_owner(
    tmp_path: Path, db_session: AsyncSession, db_session_factory: Any
) -> None:
    owner = uuid.uuid4()
    storage = FakeStorage()
    settings = Settings(secret_key="x" * 44, workspace_root=str(tmp_path))
    ws = LocalWorkspace(settings, storage, uuid.uuid4(), "run-pub")
    await ws.put_file("报告.txt", "发布内容")

    tools = workspace_tools(ws, db_session_factory, owner_id=owner, settings=settings)
    publish = next(tool for tool in tools if tool.name == "publish_file")
    ctx = _Ctx()
    result = await publish.function(ctx, "报告.txt")

    assert result["name"] == "报告.txt"
    assert result["size"] == len("发布内容".encode())
    assert len(ctx.events) == 1
    media = ctx.events[0].media[0]
    assert media.file_id == result["file_id"]
    assert media.origin == "workspace"
    async with db_session_factory() as db:
        record = await db.get(FileRecord, uuid.UUID(result["file_id"]))
        assert record is not None and record.owner_id == owner
        assert record.name == "报告.txt"
        blob = await db.get(Blob, record.blob_hash)
        assert blob is not None
        assert storage.objects[blob.storage_key] == "发布内容".encode()


async def test_tool_bundle_enables_read_image_only_with_storage_and_vision(
    tmp_path: Path, db_session_factory: Any
) -> None:
    settings = Settings(secret_key="x" * 44, workspace_root=str(tmp_path))
    with_storage = LocalWorkspace(settings, FakeStorage(), uuid.uuid4(), "run-a")

    def names(workspace: Any, profile: Any = None) -> set[str]:
        bundle = build_tool_bundle(
            TestModel(call_tools=[], profile=profile),
            workspace=workspace,
            session_factory=db_session_factory,
            owner_id=None,
            settings=settings,
            run_id=None,
            image_model_id=None,
            enable_image_generation=False,
            enable_web_search=False,
            offer_workspace_tools=True,
        )
        return {tool.name for tool in bundle.tools}

    assert "read_image" in names(with_storage)

    bare = LocalWorkspace(settings, None, uuid.uuid4(), "run-b")
    assert "read_image" not in names(bare)

    assert "read_image" not in names(with_storage, {"supports_image_input": False})


async def test_publish_file_errors(tmp_path: Path, db_session_factory: Any) -> None:
    settings = Settings(secret_key="x" * 44, workspace_root=str(tmp_path))
    ws = LocalWorkspace(settings, FakeStorage(), uuid.uuid4(), "run-pub2")
    publish = next(
        tool
        for tool in workspace_tools(ws, db_session_factory, owner_id=None, settings=settings)
        if tool.name == "publish_file"
    )
    missing = await publish.function(_Ctx(), "nope.bin")
    assert "不在工作区" in missing["error"]

    await ws.put_file("big.bin", "x" * 2048)
    small = Settings(secret_key="x" * 44, workspace_root=str(tmp_path), max_upload_bytes=1024)
    publish_small = next(
        tool
        for tool in workspace_tools(ws, db_session_factory, owner_id=None, settings=small)
        if tool.name == "publish_file"
    )
    too_big = await publish_small.function(_Ctx(), "big.bin")
    assert "上限" in too_big["error"]

    bare = LocalWorkspace(settings, None, uuid.uuid4(), "run-pub3")
    await bare.put_file("a.txt", "hi")
    publish_bare = next(
        tool
        for tool in workspace_tools(bare, db_session_factory, owner_id=None, settings=settings)
        if tool.name == "publish_file"
    )
    assert "对象存储未启用" in (await publish_bare.function(_Ctx(), "a.txt"))["error"]


async def test_list_files_lists_direct_children_and_errors(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    await ws.put_file("notes/a.md", "hi")
    await ws.put_file("root.txt", "hi")
    nested = await ws.list_files("notes")
    assert nested["directory"] == "notes"
    assert [entry["name"] for entry in nested["entries"]] == ["a.md"]
    root = await ws.list_files()
    assert {entry["name"] for entry in root["entries"]} == {"notes", "root.txt"}
    assert next(entry for entry in root["entries"] if entry["name"] == "notes")["directory"] is True
    missing = await ws.list_files("nope")
    assert "error" in missing


# ------------------------------------------------------------------ SandboxWorkspace


class _FakeFormats:
    """files.* 的假件：记账写入 / 读取 / 目录列举。"""

    def __init__(self) -> None:
        self.written: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.reads: list[str] = []

    async def make_dir(self, path: str) -> None:
        self.dirs.add(path)

    async def write(self, path: str, data: bytes, request_timeout: float | None = None) -> None:
        self.written[path] = data

    async def read(self, path: str, format: str = "text") -> bytes:
        self.reads.append(path)
        if path not in self.written:
            raise OSError(f"no file {path}")
        return self.written[path]

    async def get_info(self, path: str) -> Any:
        if path not in self.written:
            raise OSError(f"no file {path}")
        return SimpleNamespace(name=path.rsplit("/", 1)[-1], size=len(self.written[path]))

    async def list(self, path: str) -> list[Any]:
        prefix = path.rstrip("/") + "/"
        entries: dict[str, bool] = {}
        for full in [*self.written, *self.dirs]:
            if not full.startswith(prefix):
                continue
            rest = full[len(prefix) :]
            if not rest:
                continue
            name, sep, _ = rest.partition("/")
            entries[name] = entries.get(name, False) or bool(sep) or full in self.dirs
        return [SimpleNamespace(name=name, is_dir=is_dir) for name, is_dir in entries.items()]


class _FakeCommands:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.calls: list[dict[str, Any]] = []

    async def run(self, command: str, cwd: str | None = None, timeout: float = 60) -> Any:  # noqa: ASYNC109
        self.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return SimpleNamespace(exit_code=self.exit_code, stdout="did run", stderr="")


class _FakeSandbox:
    sandbox_id = "sbx-fake-1"

    def __init__(self) -> None:
        self.files = _FakeFormats()
        self.commands = _FakeCommands()

    async def beta_pause(self) -> None:
        self.paused = True

    async def kill(self) -> None:
        self.killed = True


def _record(
    db_session: AsyncSession,
    name: str,
    body: bytes,
    *,
    owner_id: uuid.UUID | None = None,
) -> FileRecord:
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    db_session.add(Blob(hash_id=digest, size=len(body), storage_key=f"blobs/{uuid.uuid4().hex}"))
    record = FileRecord(name=name, blob_hash=digest, content_type="text/plain", owner_id=owner_id)
    db_session.add(record)
    return record


async def test_sandbox_resolve_files_writes_storage_bytes(db_session: AsyncSession) -> None:
    """load_files 从对象存储取字节，再经 files.write 推到 envd。"""
    body = "文件内容".encode()
    record = _record(db_session, "说明.txt", body)
    await db_session.commit()

    storage = FakeStorage()
    blob = await db_session.get(Blob, record.blob_hash)
    assert blob is not None
    await storage.put(blob.storage_key, body, None)

    sandbox = _FakeSandbox()
    ws = SandboxWorkspace(storage, uuid.uuid4(), "run-3", sandbox)
    entries = await ws.resolve_files(db_session, [str(record.id), "not-a-uuid"])

    assert entries[0]["saved_as"] == "说明.txt"
    assert entries[0]["size"] == len(body)
    assert sandbox.files.written == {f"{ws.root}/说明.txt": body}
    assert sandbox.commands.calls == []
    assert "error" in entries[1]


async def test_sandbox_resolve_files_reports_storage_failure(db_session: AsyncSession) -> None:
    record = _record(db_session, "missing.txt", b"gone")
    await db_session.commit()

    sandbox = _FakeSandbox()
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-4", sandbox)
    entries = await ws.resolve_files(db_session, [str(record.id)])

    assert "读取对象存储失败" in entries[0]["error"]
    assert sandbox.files.written == {}


class _BrokenFiles(_FakeFormats):
    async def write(self, path: str, data: bytes, request_timeout: float | None = None) -> None:
        raise OSError("envd down")


async def test_sandbox_resolve_files_reports_write_failure(db_session: AsyncSession) -> None:
    body = b"x"
    record = _record(db_session, "x.txt", body)
    await db_session.commit()

    storage = FakeStorage()
    blob = await db_session.get(Blob, record.blob_hash)
    assert blob is not None
    await storage.put(blob.storage_key, body, None)

    sandbox = _FakeSandbox()
    sandbox.files = _BrokenFiles()
    ws = SandboxWorkspace(storage, uuid.uuid4(), "run-5", sandbox)
    entries = await ws.resolve_files(db_session, [str(record.id)])

    assert "写入沙箱失败" in entries[0]["error"]


async def test_sandbox_resolve_files_rejects_other_owner(db_session: AsyncSession) -> None:
    record = _record(db_session, "private.txt", b"secret", owner_id=uuid.uuid4())
    await db_session.commit()

    sandbox = _FakeSandbox()
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-owner", sandbox)
    entries = await ws.resolve_files(db_session, [str(record.id)], owner_id=uuid.uuid4())

    assert entries[0]["error"] == "文件不存在或已被删除"
    assert sandbox.files.written == {}


async def test_sandbox_workspace_write_read() -> None:
    sandbox = _FakeSandbox()
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-9", sandbox)
    saved = await ws.put_file("out.md", "沙箱产物")
    assert saved["saved_as"] == "out.md"
    assert saved["size"] == len("沙箱产物".encode())
    assert sandbox.files.written[f"{ws.root}/out.md"] == "沙箱产物".encode()
    text = await ws.read_file("out.md")
    assert any("沙箱产物" in line for line in text["lines"])
    assert await ws.read_binary("out.md") == "沙箱产物".encode()
    commands = await ws.run_command("ls", 30)
    assert commands["exit_code"] == 0


async def test_sandbox_list_files_lists_direct_children() -> None:
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-list", _FakeSandbox())
    await ws.put_file("notes/a.md", "hi")
    await ws.put_file("root.txt", "hi")

    root = await ws.list_files()
    assert root["directory"] == "."
    assert {entry["name"]: entry["directory"] for entry in root["entries"]} == {
        "notes": True,
        "root.txt": False,
    }
    nested = await ws.list_files("notes")
    assert nested["directory"] == "notes"
    assert [entry["name"] for entry in nested["entries"]] == ["a.md"]


async def test_sandbox_read_binary_checks_size_before_reading() -> None:
    sandbox = _FakeSandbox()
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-size", sandbox)
    await ws.put_file("big.bin", "0123456789")

    with pytest.raises(WorkspaceError, match="上限"):
        await ws.read_binary("big.bin", max_bytes=5)
    assert sandbox.files.reads == []
    assert await ws.read_binary("big.bin", max_bytes=10) == b"0123456789"


async def test_sandbox_workspace_starts_lazily_and_reuses() -> None:
    sandbox = _FakeSandbox()
    sandbox.files = _FakeFormats()
    calls = 0

    async def factory() -> _FakeSandbox:
        nonlocal calls
        calls += 1
        return sandbox

    ws = SandboxWorkspace(
        FakeStorage(),
        uuid.uuid4(),
        "run-lazy",
        sandbox_factory=factory,
    )
    assert calls == 0
    await ws.put_file("a.txt", "hello")
    assert calls == 1
    await ws.run_command("ls", 5)
    assert calls == 1
    assert sandbox.files.written[f"{ws.root}/a.txt"] == b"hello"


# ------------------------------------------------------------------ 兜底


async def test_default_run_command_is_unavailable(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    result = await ws.run_command("ls")
    assert "error" in result


async def test_load_files_absent_without_storage(tmp_path: Path) -> None:
    ws = LocalWorkspace(SimpleNamespace(workspace_root=str(tmp_path)), None, uuid.uuid4(), "run-2")
    result = await ws.resolve_files(None, ["abc"])
    assert "对象存储未启用" in result[0]["error"]


async def test_workspace_dir_is_stable_across_runs(tmp_path: Path) -> None:
    """目录按会话划分：上一轮写的文件，下一轮还要读得到。"""
    session = uuid.uuid4()
    first = SandboxWorkspace(FakeStorage(), session, "run-a", _FakeSandbox())
    second = SandboxWorkspace(FakeStorage(), session, "run-b", _FakeSandbox())
    assert first.root == second.root
    assert str(session) in first.root

    other = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-c", _FakeSandbox())
    assert other.root != first.root


def test_local_workspace_dir_is_stable_across_runs(tmp_path: Path) -> None:
    session = uuid.uuid4()
    settings = SimpleNamespace(workspace_root=str(tmp_path))
    first = LocalWorkspace(settings, FakeStorage(), session, "run-a")
    second = LocalWorkspace(settings, FakeStorage(), session, "run-b")
    assert first.root == second.root == tmp_path / str(session)


def test_sandbox_requires_both_key_and_platform_switch() -> None:
    from app.sandbox.workspace import sandbox_enabled

    settings = SimpleNamespace(sandbox_api_key="e2b-test", feature_sandbox_enabled=False)
    assert sandbox_enabled(settings) is False

    settings.feature_sandbox_enabled = True
    assert sandbox_enabled(settings) is True

    settings.sandbox_api_key = None
    assert sandbox_enabled(settings) is False
