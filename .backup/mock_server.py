"""Randomized mock backend: streaming text, errors, approvals and external calls."""

import asyncio
import json
import os
import random
import struct
import zlib
from uuid import uuid4

from pydantic_ai import Tool
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelResponse,
    TextContent,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.agents.base import BaseAgent
from app.services import run as run_service
from app.services.model_factory import ModelFactory, ResolvedModel


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class MockAgent(BaseAgent):
    name = "mock-agent"

    def default_tools(self) -> list[Tool]:
        def delete_file(path: str) -> str:
            return f"deleted {path}"

        def write_file(path: str, content: str) -> str:
            return f"wrote {len(content)} bytes to {path}"

        def archive_log(path: str, days: int) -> str:
            return f"archived {path} for {days} days"

        def fetch_price_a(symbol: str) -> str:
            raise CallDeferred(metadata={"source": "vendor", "symbol": symbol})

        def fetch_price_b(symbol: str) -> str:
            raise CallDeferred(metadata={"source": "vendor", "symbol": symbol})

        def fetch_weather(city: str) -> str:
            raise CallDeferred(metadata={"source": "weather-api", "city": city})

        def lookup_order(order_id: str) -> str:
            raise CallDeferred(metadata={"source": "order-center", "order_id": order_id})

        def make_chart(title: str) -> BinaryContent:
            color = (random.randint(60, 220), random.randint(60, 220), random.randint(60, 220))
            size = (random.randint(180, 260), random.randint(90, 150))
            return BinaryContent(data=_png(*size, color), media_type="image/png")

        return [
            *super().default_tools(),
            Tool(delete_file, name="delete_file", requires_approval=True),
            Tool(write_file, name="write_file", requires_approval=True),
            Tool(archive_log, name="archive_log", requires_approval=True),
            Tool(fetch_price_a, name="fetch_price_a"),
            Tool(fetch_price_b, name="fetch_price_b"),
            Tool(fetch_weather, name="fetch_weather"),
            Tool(lookup_order, name="lookup_order"),
            Tool(make_chart, name="make_chart"),
        ]


APPROVAL_CALLS = [
    ("delete_file", lambda: {"path": random.choice(["tmp/cache.log", "dist/old.js", "tmp/upload.tmp"])}),
    (
        "write_file",
        lambda: {
            "path": random.choice(["src/config.py", "README.md", "app/settings.py"]),
            "content": f"# patched by mock #{uuid4().hex[:4]}\n",
        },
    ),
    (
        "archive_log",
        lambda: {
            "path": random.choice(["logs/app.log", "logs/worker.log", "logs/access.log"]),
            "days": random.choice([7, 30, 90]),
        },
    ),
]

EXTERNAL_CALLS = [
    ("fetch_price_a", lambda: {"symbol": random.choice(["AAA", "BTC", "ETH"])}),
    ("fetch_price_b", lambda: {"symbol": random.choice(["BBB", "SOL", "DOGE"])}),
    ("fetch_weather", lambda: {"city": random.choice(["上海", "东京", "柏林"])}),
    ("lookup_order", lambda: {"order_id": f"ORD-{random.randint(1000, 9999)}"}),
]


def _part_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, TextContent):
                parts.append(item.content)
            elif isinstance(getattr(item, "text", None), str):
                parts.append(item.text)
        return " ".join(parts)
    return str(content or "")


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                return _part_text(part.content)
    return ""


def _round_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    """本轮（最后一条用户提问之后）已经回填的工具结果。"""
    last_user = -1
    for index, message in enumerate(messages):
        if any(isinstance(part, UserPromptPart) for part in message.parts):
            last_user = index
    return [
        part
        for message in messages[last_user + 1 :]
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def _returned(messages: list[ModelMessage], tool_name: str) -> int:
    """本轮某个工具已经回填过几次：用来在清单跑完后再触发别的场景。"""
    return sum(1 for part in _round_returns(messages) if part.tool_name == tool_name)


def _has_tool_result(messages: list[ModelMessage]) -> bool:
    return len(_round_returns(messages)) > 0


def _random_text() -> str:
    tag = uuid4().hex[:4]
    value = random.randint(10, 99)
    return random.choice(
        [
            f"Mock 回应 #{tag}：已完成当前操作。",
            f"**随机结果 #{tag}**：抽到的数字是 {value}。\n\n需要我继续做点什么吗？",
            (
                f"## 随机清单 #{tag}\n\n"
                f"- 检查了 {random.randint(2, 8)} 个文件\n"
                f"- 命中 {random.randint(1, 5)} 条规则\n"
                f"- 建议保留 {value}% 的缓存\n\n"
                "```python\n"
                f"print('mock {tag}')\n"
                "```"
            ),
            (
                f"我随机挑了三件事：\n\n"
                "1. 先看最近一次失败日志\n"
                "2. 再对比两个分支的差异\n"
                f"3. 最后生成一份包含 {value} 个条目的报告\n\n"
                "你想先做哪一件？"
            ),
            (
                f"```json\n"
                f'{{"mock": "{tag}", "value": {value}, "ok": true}}\n'
                "```\n\n"
                "这是一个随机 JSON 代码块，用来检查代码渲染。"
            ),
            (
                f"表格预览 #{tag}\n\n"
                "| 指标 | 数值 |\n"
                "| --- | --- |\n"
                f"| 命中率 | {value}% |\n"
                f"| 延迟 | {random.randint(80, 400)} ms |\n"
                f"| 队列 | {random.randint(0, 9)} |"
            ),
            (
                f"长文随机回答 #{tag}。"
                + "这是一段用来观察流式输出、滚动和复制按钮的文本。" * random.randint(4, 8)
                + f"\n\n最后一行：随机数 {value}。"
            ),
        ]
    )


def _long_text() -> str:
    tag = uuid4().hex[:4]
    return (
        f"## 长文 Mock #{tag}\n\n"
        + "\n\n".join(
            f"第 {index} 段：这是随机生成的内容，用来检查长消息的滚动和自动跟随。"
            for index in range(1, 7)
        )
        + "\n\n| 项目 | 值 |\n| --- | --- |\n"
        + f"| 编号 | {tag} |\n| 随机值 | {random.randint(100, 999)} |"
    )


def _requested_count(text: str, maximum: int) -> int:
    for word, count in (("三个", 3), ("3个", 3), ("两个", 2), ("2个", 2), ("一个", 1), ("1个", 1)):
        if word in text:
            return min(count, maximum)
    return random.randint(1, maximum)


def _tool_calls(text: str) -> dict[int, DeltaToolCall]:
    """随机 1-3 个需要审批的工具调用；说“两个审批”可以固定数量。"""
    count = _requested_count(text, min(3, len(APPROVAL_CALLS)))
    picks = random.sample(APPROVAL_CALLS, count)
    return {
        index: DeltaToolCall(
            name=name,
            json_args=json.dumps(args()),
            tool_call_id=f"call_approval_{uuid4().hex[:8]}",
        )
        for index, (name, args) in enumerate(picks)
    }


def _external_calls(text: str) -> dict[int, DeltaToolCall]:
    """随机 1-4 个外部调用；说“三个查询”可以固定数量。"""
    count = _requested_count(text, len(EXTERNAL_CALLS))
    picks = random.sample(EXTERNAL_CALLS, count)
    return {
        index: DeltaToolCall(
            name=name,
            json_args=json.dumps(args()),
            tool_call_id=f"call_external_{uuid4().hex[:8]}",
        )
        for index, (name, args) in enumerate(picks)
    }


def _mixed_calls() -> dict[int, DeltaToolCall]:
    approval_name, approval_args = random.choice(APPROVAL_CALLS)
    call_name, call_args = random.choice(EXTERNAL_CALLS)
    return {
        0: DeltaToolCall(
            name=approval_name,
            json_args=json.dumps(approval_args()),
            tool_call_id=f"call_approval_{uuid4().hex[:8]}",
        ),
        1: DeltaToolCall(
            name=call_name,
            json_args=json.dumps(call_args()),
            tool_call_id=f"call_external_{uuid4().hex[:8]}",
        ),
    }


PLAN_ITEMS = ["梳理现有实现", "接上后端工具", "做前端悬浮窗"]


def _plan_items(text: str) -> list[str]:
    """「清单10步」指定步数，用来看浮窗展开后的滚动浏览。"""
    digits = "".join(char for char in text if char.isdigit())
    count = min(int(digits), 12) if digits else len(PLAN_ITEMS)
    if count == len(PLAN_ITEMS):
        return PLAN_ITEMS
    return [f"第 {index + 1} 步：这一步的描述会长一点，用来撑满浮窗高度" for index in range(count)]


def _plan_call(step: int, items: list[str]) -> DeltaToolCall:
    """清单走到第 step 步：前 step 项已完成，第 step 项进行中。"""
    return DeltaToolCall(
        name="plan_set",
        json_args=json.dumps(
            {"items": items, "done": list(range(step)), "active": step},
            ensure_ascii=False,
        ),
        tool_call_id=f"call_plan_{uuid4().hex[:8]}",
    )


def _scenario(text: str) -> str:
    if "混合" in text:
        return "mixed"
    if "审批" in text or "删除" in text or "写入" in text:
        return "approval"
    if "查询" in text or "调用" in text or "价格" in text or "天气" in text:
        return "call"
    return random.choices(
        ["text", "approval", "call", "mixed"],
        weights=[55, 20, 20, 5],
        k=1,
    )[0]


def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    text = _last_user_text(messages)
    if "长文" in text:
        reply = _long_text()
    elif "代码" in text:
        reply = "```python\n" + "\n".join(
            f"print('mock line {index}: {random.randint(1, 999)}')" for index in range(1, 6)
        ) + "\n```"
    else:
        reply = _random_text()
    return ModelResponse(parts=[TextPart(reply)])


def _preview_html() -> str:
    color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    return (
        '<style>body{font:14px/1.6 system-ui;margin:24px}'
        f"b{{color:{color}}}</style>"
        "<h3>Mock 预览</h3>"
        f"<p>主色 <b>{color}</b>，随机数 {random.randint(10, 99)}。</p>"
        '<button onclick="this.textContent+=1">点我 +1</button>'
    )


def _ask_args() -> dict[str, object]:
    """一道单选 + 一道多选，方便看答题卡的两种形态。"""
    return {
        "questions": [
            {
                "question": "这一步先做什么?",
                "options": [
                    {"label": "A 写脚本", "description": "先把逻辑跑通，验证可行性"},
                    {"label": "B 画原型", "description": "先定形态，再谈实现"},
                ],
            },
            {
                "question": "要不要顺手补测试?",
                "options": [
                    {"label": "单元测试", "description": "覆盖主流程就行"},
                    {"label": "端到端", "description": "慢一点但更稳"},
                    {"label": "先不补", "description": "手工验过再算"},
                ],
                "multi_select": True,
            },
        ]
    }


async def respond_stream(messages: list[ModelMessage], _info: AgentInfo):
    text = _last_user_text(messages)
    if "报错" in text:
        yield "半截回答："
        raise RuntimeError("Mock 模型故意报错")

    if _has_tool_result(messages):
        reply = random.choice(
            [
                f"工具结果已回填 #{uuid4().hex[:4]}：已完成当前操作。",
                f"外部结果收到了 #{uuid4().hex[:4]}，随机结论是 {random.choice(['继续', '重试', '观察'])}。",
            ]
        )
    elif "长文" in text:
        reply = _long_text()
    elif "代码" in text:
        reply = "```python\n" + "\n".join(
            f"print('mock line {index}: {random.randint(1, 999)}')" for index in range(1, 6)
        ) + "\n```"
    else:
        reply = _random_text()

    slow = "超慢" in text
    medium = "慢速" in text
    forced_text = slow or medium or "长文" in text or "代码" in text
    step = sum(1 for part in _round_returns(messages) if part.tool_name == "plan_set")
    items = _plan_items(text)
    if "清单" in text and step <= len(items):
        await asyncio.sleep(0.7)
        yield {0: _plan_call(step, items)}
        return
    # 一批里同时给审批、提问、自动回填三种卡：面板要一页一项，不叠在一起
    if "混合卡片" in text and _returned(messages, "delete_file") == 0:
        yield {
            0: DeltaToolCall(
                name="delete_file",
                json_args=json.dumps({"path": "tmp/cache.log"}),
                tool_call_id=f"call_approval_{uuid4().hex[:8]}",
            ),
            1: DeltaToolCall(
                name="ui_ask_user_question",
                json_args=json.dumps(_ask_args(), ensure_ascii=False),
                tool_call_id=f"call_ask_{uuid4().hex[:8]}",
            ),
            2: DeltaToolCall(
                name="fetch_price_a",
                json_args=json.dumps({"symbol": "BTC"}),
                tool_call_id=f"call_external_{uuid4().hex[:8]}",
            ),
        }
        return
    if not _has_tool_result(messages) and "提问" in text:
        yield {
            0: DeltaToolCall(
                name="ui_ask_user_question",
                json_args=json.dumps(_ask_args(), ensure_ascii=False),
                tool_call_id=f"call_ask_{uuid4().hex[:8]}",
            )
        }
        return
    if not _has_tool_result(messages) and "预览" in text:
        yield {
            0: DeltaToolCall(
                name="ui_open_html_preview",
                json_args=json.dumps(
                    {"title": f"随机预览 #{uuid4().hex[:4]}", "html": _preview_html()},
                    ensure_ascii=False,
                ),
                tool_call_id=f"call_preview_{uuid4().hex[:8]}",
            )
        }
        return
    if not _has_tool_result(messages) and ("图表" in text or "图片" in text):
        yield {
            0: DeltaToolCall(
                name="make_chart",
                json_args=json.dumps({"title": f"随机图表 #{uuid4().hex[:4]}"}),
                tool_call_id=f"call_chart_{uuid4().hex[:8]}",
            )
        }
        return
    if not _has_tool_result(messages) and not forced_text:
        scenario = _scenario(text)
        if scenario == "approval":
            yield _tool_calls(text)
            return
        if scenario == "call":
            yield _external_calls(text)
            return
        if scenario == "mixed":
            yield _mixed_calls()
            return

    for char in reply:
        await asyncio.sleep(0.8 if slow else 0.25 if medium else random.uniform(0.002, 0.012))
        yield char


resolved = ResolvedModel(
    name="mock",
    model=FunctionModel(function=respond, stream_function=respond_stream),
    settings={},
    context_window=None,
    supports_tools=True,
)
ModelFactory.create = lambda self, record: resolved  # noqa: ARG005
run_service.BaseAgent = MockAgent

from app.main import app  # noqa: E402
import uvicorn  # noqa: E402

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["MOCK_PORT"]),
    log_level="warning",
)
