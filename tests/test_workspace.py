"""工作区工具与本地工作区动作：读写、范围读、列表、收产物、安全约束。"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.workspace import workspace_tools
from app.core.config import Settings
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.services.workspace import (
    LocalWorkspace,
    SandboxWorkspace,
    WorkspaceError,
    open_sandbox_workspace,
    text_read,
)
from tests.test_files import FakeStorage

LONG_TEXT = "alpha\nbeta\ngamma\ndelta\nepsilon\n"


def _local(tmp_path: Path, run_id: str = "run-1") -> LocalWorkspace:
    settings = SimpleNamespace(workspace_root=str(tmp_path))
    return LocalWorkspace(settings, FakeStorage(), uuid.uuid4(), run_id)


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


async def test_put_file_dedups_name_and_read_write_roundtrip(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    first = await ws.put_file("报告.md", "内容一")
    assert first["saved_as"] == "报告.md"
    second = await ws.put_file("报告.md", "内容二")
    assert second["saved_as"] == "报告 (1).md"
    listed = await ws.list_files()
    assert {f["path"] for f in listed["files"]} == {"报告.md", "报告 (1).md"}
    text = await ws.read_file("报告.md")
    assert any("内容一" in line for line in text["lines"])
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


async def test_collect_artifacts_and_cleanup(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    await ws.put_file("out.csv", "a,b\n1,2")
    await ws.put_file("keep.md", "")
    artifacts = await ws.collect_artifacts()
    assert [name for name, _data, _mime in artifacts] == ["out.csv"]  # 空文件不上收
    await ws.cleanup()
    assert not ws.root.exists()


async def test_publish_file_uploads_as_owner_and_skips_sync(
    tmp_path: Path, db_session: AsyncSession, db_session_factory: Any
) -> None:
    owner = uuid.uuid4()
    storage = FakeStorage()
    settings = Settings(secret_key="x" * 44, workspace_root=str(tmp_path))
    ws = LocalWorkspace(settings, storage, uuid.uuid4(), "run-pub")
    await ws.put_file("报告.txt", "发布内容")

    tools = workspace_tools(ws, db_session_factory, owner_id=owner, settings=settings)
    publish = next(tool for tool in tools if tool.name == "publish_file")
    result = await publish.function("报告.txt")

    assert result["name"] == "报告.txt"
    assert result["size"] == len("发布内容".encode())
    async with db_session_factory() as db:
        record = await db.get(FileRecord, uuid.UUID(result["storage_key"]))
        assert record is not None and record.owner_id == owner
        assert record.name == "报告.txt"
        blob = await db.get(Blob, record.blob_hash)
        assert blob is not None
        assert storage.objects[blob.storage_key] == "发布内容".encode()

    # 已经单独发布过的文件，run 收尾时不再重复上传
    assert await ws.collect_artifacts() == []


async def test_publish_file_errors(tmp_path: Path, db_session_factory: Any) -> None:
    settings = Settings(secret_key="x" * 44, workspace_root=str(tmp_path))
    ws = LocalWorkspace(settings, FakeStorage(), uuid.uuid4(), "run-pub2")
    publish = next(
        tool
        for tool in workspace_tools(ws, db_session_factory, owner_id=None, settings=settings)
        if tool.name == "publish_file"
    )
    missing = await publish.function("nope.bin")
    assert "不在工作区" in missing["error"]

    await ws.put_file("big.bin", "x" * 2048)
    small = Settings(
        secret_key="x" * 44, workspace_root=str(tmp_path), max_upload_bytes=1024
    )
    publish_small = next(
        tool
        for tool in workspace_tools(ws, db_session_factory, owner_id=None, settings=small)
        if tool.name == "publish_file"
    )
    too_big = await publish_small.function("big.bin")
    assert "上限" in too_big["error"]

    bare = LocalWorkspace(settings, None, uuid.uuid4(), "run-pub3")
    await bare.put_file("a.txt", "hi")
    publish_bare = next(
        tool
        for tool in workspace_tools(bare, db_session_factory, owner_id=None, settings=settings)
        if tool.name == "publish_file"
    )
    assert "对象存储未启用" in (await publish_bare.function("a.txt"))["error"]


async def test_list_files_nests_and_errors(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    await ws.put_file("notes/a.md", "hi")
    nested = await ws.list_files("notes")
    assert nested["files"][0]["path"] == "notes/a.md"
    missing = await ws.list_files("nope")
    assert "error" in missing


# ------------------------------------------------------------------ SandboxWorkspace


class _FakeFormats:
    """files.* 的假件：记账写入 / 读取 / 目录列举。"""

    def __init__(self) -> None:
        self.written: dict[str, bytes] = {}
        self.objects: list[dict[str, str]] = []

    async def make_dir(self, path: str) -> None:
        self.objects.append({"path": path})

    async def write(self, path: str, data: bytes) -> None:
        self.written[path] = data

    async def read(self, path: str, format: str = "text") -> bytes:
        if path not in self.written:
            raise OSError(f"no file {path}")
        return self.written[path]

    async def list(self, path: str) -> list[Any]:
        class Entry(SimpleNamespace):
            pass

        return [Entry(name=obj["path"], is_dir=False) for obj in self.objects]


class _FakeCommands:
    async def run(self, command: str, cwd: str | None = None, timeout: float = 60) -> Any:  # noqa: ASYNC109
        return SimpleNamespace(exit_code=0, stdout="did run", stderr="")


class _FakeSandbox:
    sandbox_id = "sbx-fake-1"
    files = _FakeFormats()
    commands = _FakeCommands()

    async def beta_pause(self) -> None:
        self.paused = True

    async def kill(self) -> None:
        self.killed = True


def _record(db_session: AsyncSession, name: str, body: bytes) -> FileRecord:
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    db_session.add(
        Blob(hash_id=digest, size=len(body), storage_key=f"blobs/{uuid.uuid4().hex}")
    )
    record = FileRecord(name=name, blob_hash=digest, content_type="text/plain")
    db_session.add(record)
    return record


async def test_sandbox_resolve_keys_pushes_bytes(db_session: AsyncSession) -> None:
    body = "文件内容".encode()
    record = _record(db_session, "说明.txt", body)
    await db_session.commit()

    storage = FakeStorage()
    blob = await db_session.get(Blob, record.blob_hash)
    assert blob is not None
    await storage.put(blob.storage_key, body, None)

    sandbox = _FakeSandbox()
    sandbox.files = _FakeFormats()
    ws = SandboxWorkspace(storage, uuid.uuid4(), "run-3", sandbox)
    entries = await ws.resolve_keys(db_session, [str(record.id), "not-a-uuid"])

    assert entries[0]["saved_as"] == "说明.txt"
    assert entries[0]["size"] == len(body)
    assert sandbox.files.written[f"{ws.root}/说明.txt"] == body
    assert "error" in entries[1]


async def test_sandbox_resolve_keys_reports_download_failure(db_session: AsyncSession) -> None:
    body = b"gone"
    record = _record(db_session, "missing.txt", body)
    await db_session.commit()

    sandbox = _FakeSandbox()
    sandbox.files = _FakeFormats()
    ws = SandboxWorkspace(FakeStorage(), uuid.uuid4(), "run-4", sandbox)
    entries = await ws.resolve_keys(db_session, [str(record.id)])

    assert "下载到沙箱失败" in entries[0]["error"]
    assert sandbox.files.written == {}


async def test_sandbox_workspace_write_read_collect() -> None:
    sandbox = _FakeSandbox()
    ws = await open_sandbox_workspace(FakeStorage(), uuid.uuid4(), "run-9", sandbox)
    saved = await ws.put_file("out.md", "沙箱产物")
    assert saved["saved_as"] == "out.md"
    assert ws.produced_files, "沙箱写文件要记账供收产物"
    assert sandbox.files.written[f"{ws.root}/out.md"] == "沙箱产物".encode()
    text = await ws.read_file("out.md")
    assert any("沙箱产物" in line for line in text["lines"])
    assert await ws.read_binary("out.md") == "沙箱产物".encode()
    commands = await ws.run_command("ls", 30)
    assert commands["exit_code"] == 0
    artifacts = await ws.collect_artifacts()
    assert artifacts and artifacts[0][0] == "out.md"
    ws.mark_published("out.md")
    assert await ws.collect_artifacts() == []


# ------------------------------------------------------------------ 兜底


async def test_default_run_command_is_unavailable(tmp_path: Path) -> None:
    ws = _local(tmp_path)
    result = await ws.run_command("ls")
    assert "error" in result


async def test_load_files_absent_without_storage(tmp_path: Path) -> None:
    ws = LocalWorkspace(
        SimpleNamespace(workspace_root=str(tmp_path)), None, uuid.uuid4(), "run-2"
    )
    result = await ws.resolve_keys(None, ["abc"])
    assert "对象存储未启用" in result[0]["error"]
