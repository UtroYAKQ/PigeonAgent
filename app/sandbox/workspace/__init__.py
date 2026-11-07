"""工作区：本地临时目录与 e2b 兼容沙箱，两种模式的工具形状一致。"""

from app.sandbox.workspace.base import RunWorkspace
from app.sandbox.workspace.common import WorkspaceError, text_read
from app.sandbox.workspace.local import (
    LocalWorkspace,
    local_workspace_root,
    purge_session_workspace,
)
from app.sandbox.workspace.sandbox import (
    SandboxWorkspace,
    can_use_sandbox,
    connect_sandbox,
    create_sandbox,
    sandbox_ttl,
)

__all__ = [
    "LocalWorkspace",
    "RunWorkspace",
    "SandboxWorkspace",
    "WorkspaceError",
    "can_use_sandbox",
    "connect_sandbox",
    "create_sandbox",
    "local_workspace_root",
    "purge_session_workspace",
    "sandbox_ttl",
    "text_read",
]
