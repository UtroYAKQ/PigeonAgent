from enum import StrEnum


class RunStatus(StrEnum):
    """一次 run 的生命周期。"""

    RUNNING = "running"
    COMPLETED = "completed"
    # 以 DeferredToolRequests 结束，等待审批 / 外部结果
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunKind(StrEnum):
    """run 在树里的用途；分支导航只把 turn 当版本。"""

    TURN = "turn"
    RESUME = "resume"


class ItemType(StrEnum):
    """run.content 里的 item 类型。"""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    RESOURCE = "resource"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    APPROVAL_REQUEST = "approval_request"
    CALL_REQUEST = "call_request"
    CUSTOM = "custom"
