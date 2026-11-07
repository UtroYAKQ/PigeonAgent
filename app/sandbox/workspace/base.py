"""工作区抽象接口：两种模式形状一致，差异只在字节落在哪。"""

from __future__ import annotations

import abc
import uuid
from typing import TYPE_CHECKING, Any

from app.infra.files.storage import ObjectStorage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RunWorkspace(abc.ABC):
    """一轮 run 的工作区；生命周期与 execute_run 的 try 块同进退。"""

    def __init__(
        self,
        storage: ObjectStorage | None,
        session_id: uuid.UUID,
        run_id: str,
    ) -> None:
        self.storage = storage
        self.session_id = session_id
        self.run_id = run_id

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """给模型的一句话：这是什么样的工作区，路径怎么写。"""

    def touch(self) -> None:  # noqa: B027 - 本地模式无须刷新，默认空实现
        """工具活动钩子，沙箱模式刷新空闲计时，本地模式无事可做。"""

    @abc.abstractmethod
    async def resolve_files(
        self, db: AsyncSession, file_ids: list[str], *, owner_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """file_id → 实体化记录；只允许会话主人自己的文件。"""

    @abc.abstractmethod
    async def put_file(self, name: str, content: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_binary(self, name: str, *, max_bytes: int | None = None) -> bytes:
        """按相对路径读原始字节；超过 max_bytes 时抛 WorkspaceError。"""

    @abc.abstractmethod
    async def list_files(self, subdir: str = ".") -> dict[str, Any]: ...

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        return {"error": "当前模式是本地工作区，没有命令执行；配好沙箱（SANDBOX_API_KEY）再来"}

    async def cleanup(self) -> None:  # noqa: B027 - 沙箱随 kill 一起没，不需要额外清理
        ...
