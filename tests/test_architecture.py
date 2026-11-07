from __future__ import annotations

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "agents" / "tools"
# item 落库只允许走 turn；工具只能返回值或发类型化事件。
FORBIDDEN = (
    "app.agents.runtime.store",
    "app.services.run_store",
    "SessionStore",
    "append_items",
    "record_compaction",
)


def test_agent_tools_do_not_persist_run_items() -> None:
    offenders = [
        f"{path.relative_to(TOOLS_DIR)}: {token}"
        for path in TOOLS_DIR.rglob("*.py")
        for token in FORBIDDEN
        if token in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
