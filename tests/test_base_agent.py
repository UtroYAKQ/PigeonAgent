from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic_ai import ModelRetry, Tool
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelContextWindowExceededError,
    ModelHTTPError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models.test import TestModel

from app.agents.runtime.base import BaseAgent
from app.agents.runtime.prompts import BASE_INSTRUCTIONS
from app.agents.runtime.turn import summarize_error
from app.agents.tools import get_current_time
from app.agents.tools.frontend import frontend_toolset
from app.schemas.run import FrontendTool


class EchoAgent(BaseAgent):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "回声 agent"
    instructions: ClassVar[str] = "你是回声助手。"


def test_instructions_combine_class_and_prompt() -> None:
    assert EchoAgent(TestModel()).build_instructions(None) == "你是回声助手。"
    assert EchoAgent(TestModel()).build_instructions("额外要求") == "你是回声助手。\n\n额外要求"
    assert BaseAgent(TestModel()).build_instructions(None) == BASE_INSTRUCTIONS
    assert (
        BaseAgent(TestModel()).build_instructions("只要这句") == f"{BASE_INSTRUCTIONS}\n\n只要这句"
    )


async def test_tools_are_loaded_and_called() -> None:
    calls: list[str] = []

    def record(value: str) -> str:
        calls.append(value)
        return f"recorded {value}"

    agent = EchoAgent(TestModel(), tools=[Tool(record, name="record", description="记录一个值")])
    await agent.run("记一下")

    assert len(calls) == 1


def test_default_tools_expose_current_time() -> None:
    assert [tool.name for tool in BaseAgent(TestModel()).default_tools()] == [
        "get_current_time",
    ]


def test_current_time_defaults_to_local_zone() -> None:
    info = get_current_time()
    assert info["utc_offset"] == datetime.now().astimezone().strftime("%z")
    assert info["date"] in info["iso"]


def test_current_time_honors_requested_zone() -> None:
    assert get_current_time("UTC")["utc_offset"] == "+0000"


def test_current_time_rejects_unknown_zone() -> None:
    with pytest.raises(ModelRetry):
        get_current_time("Mars/Olympus")


def test_current_time_reports_utc_alongside_local() -> None:
    assert get_current_time()["utc"].endswith("+00:00")
    assert get_current_time()["utc"][:10] == datetime.now(UTC).date().isoformat()


def test_usage_limit_error_is_rephrased() -> None:
    error = UsageLimitExceeded("The next request would exceed the request_limit of 50.")
    summary = summarize_error(error)
    assert summary.code == "usage_limit_exceeded"
    assert "轮次" in summary.message


def test_exhausted_tool_retries_are_rephrased() -> None:
    error = UnexpectedModelBehavior("Tool 'ui_open_html_preview' exceeded max retries count of 0.")
    summary = summarize_error(error)
    assert summary.code == "tool_arguments_incomplete"
    assert "工具参数不完整" in summary.message


def test_upstream_failures_are_classified() -> None:
    cases = [
        (ModelQuotaExceededError("m", "quota"), "quota_exceeded", False),
        (ModelRateLimitError("m", "rate"), "rate_limited", True),
        (ModelHTTPError(401, "m"), "model_auth_error", False),
        (ModelHTTPError(503, "m"), "model_server_error", True),
        (ModelContextWindowExceededError("m", "long"), "context_window_exceeded", False),
        (ContentFilterError("blocked"), "content_filter", False),
    ]
    for error, code, retryable in cases:
        summary = summarize_error(error)
        assert summary.code == code, error
        assert summary.retryable is retryable, error


async def test_frontend_toolset_gives_external_tools_retry_budget() -> None:
    tool = FrontendTool(name="ui_open_html_preview", description="预览 HTML")
    toolset = frontend_toolset([tool])
    assert toolset is not None

    tools = await toolset.get_tools(None)  # type: ignore[arg-type]

    assert [item.max_retries for item in tools.values()] == [2]
