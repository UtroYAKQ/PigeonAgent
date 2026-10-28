from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic_ai import ModelRetry, Tool
from pydantic_ai.models.test import TestModel

from app.agents.base import BaseAgent
from app.agents.tools import get_current_time


class EchoAgent(BaseAgent):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "回声 agent"
    instructions: ClassVar[str] = "你是回声助手。"


def test_instructions_combine_class_and_prompt() -> None:
    assert EchoAgent(TestModel()).build_instructions(None) == "你是回声助手。"
    assert EchoAgent(TestModel()).build_instructions("额外要求") == "你是回声助手。\n\n额外要求"
    assert BaseAgent(TestModel()).build_instructions("只要这句") == "只要这句"


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
        "plan_set",
        "plan_show",
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
