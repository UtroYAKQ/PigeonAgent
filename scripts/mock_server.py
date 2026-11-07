"""Randomized mock backend: streaming text, errors, approvals and external calls."""

# ruff: noqa: E402 — 环境变量必须在 app 的 Settings 构造前落好，import 只能排在后面

import asyncio
import json
import os
import random
import struct
import zlib
from contextlib import asynccontextmanager
from uuid import uuid4

MOCK_BUCKET = "pigeon-mock"

# 上下文压缩演示：默认给 mock 模型一个很小的窗口，方便几轮内看到 checkpointer。
# 设 MOCK_CONTEXT_WINDOW=0 可关闭；设 200 之类更小的值可以更快触发。
MOCK_CONTEXT_WINDOW = int(os.environ.get("MOCK_CONTEXT_WINDOW", "1000"))
MOCK_COMPACTION_SUMMARY = """## 对话摘要

- 用户连续发送消息，主要用于验证长消息滚动、工具步骤和 Markdown 渲染。
- 已确认页面会自动跟随最新消息，代码块、表格与引用展示正常。
- 之前的原始消息已折叠进这份摘要，后续问题可以继续基于以上结论回答。"""

# mock 固定用本地 SQLite，别被 .env 里的 Postgres 接管
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./.mock/pigeon_mock.db"
os.environ.setdefault("MOCK_PORT", "8100")
# mock 必须自包含：.env 里若配了 e2b 沙箱，也强制回落到本地工作区
os.environ["SANDBOX_API_KEY"] = ""
os.environ["SANDBOX_API_URL"] = ""
os.environ["SANDBOX_DOMAIN"] = ""
# mock 下让能力接口报告联网可用，并用本地假搜索避免真实调用 DeepSeek
os.environ["DEEPSEEK_API_KEY"] = "mock-search-key"
# mock-only Fernet key：只在本地 SQLite + 假模型环境使用，绝不能拿到线上。
os.environ.setdefault("SECRET_KEY", "oebYy8JfMq4BhSBZkELmdrmI69vgTs19bVhQwm4gmN0=")
os.environ.setdefault("ADMIN_PASSWORD", "mock-admin-password")

_mock_s3: object | None = None


def _start_mock_s3() -> None:
    """进程内 moto S3：mock 不依赖任何外部对象存储，重启即清空。"""
    global _mock_s3
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    # 无条件覆盖：.env 里可能配着真桶，mock 绝不能写进去
    os.environ.update(
        S3_ENDPOINT_URL=f"http://{host}:{port}",
        S3_BUCKET=MOCK_BUCKET,
        S3_ACCESS_KEY="mock-access-key",
        S3_SECRET_KEY="mock-secret-key",
        S3_REGION="us-east-1",
        S3_ADDRESSING_STYLE="path",
        S3_PREFIX=MOCK_BUCKET,
    )

    import boto3
    from botocore.config import Config

    boto3.session.Session(
        aws_access_key_id="mock-access-key",
        aws_secret_access_key="mock-secret-key",
        region_name="us-east-1",
    ).client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        config=Config(s3={"addressing_style": "path"}),
    ).create_bucket(Bucket=MOCK_BUCKET)
    _mock_s3 = server


_start_mock_s3()

from pydantic_ai import Tool
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelResponse,
    TextContent,
    TextPart,
    ThinkingPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from app.agents.runtime.base import BaseAgent
from app.infra.providers.llm import ModelFactory, ResolvedModel
from app.services import run as run_service


def mock_web_search(query: str, count: int = 6) -> dict[str, object]:
    """Mock 搜索工具：返回稳定的假结果，供前端联调工具表格与引用。"""
    limit = max(1, min(int(count), 10))
    if "天气" in query:
        results = [
            {
                "title": "杭州实时天气",
                "url": "https://weather.example.com/hangzhou",
                "snippet": "当前多云 19℃/湿度 69%，明后两天晴到多云。",
                "summary": "杭州当前多云，气温 19℃，湿度 69%；未来两天以晴到多云为主。",
                "site_name": "示例天气",
                "date": "2026-10-29T10:40:00+08:00",
                "authority": 3,
                "rerank_score": 2.6,
            }
        ]
    elif "Spring" in query or "spring" in query:
        results = [
            {
                "title": "Spring Cloud 版本说明",
                "url": "https://spring.io/projects/spring-cloud",
                "snippet": "2025.1.4 是当前维护中的稳定版本。",
                "summary": "Spring Cloud 2025.1.4（Oakwood）为当前维护版本，配套 Boot 4.0.x。",
                "site_name": "Spring",
                "date": "2026-10-22T00:00:00+00:00",
                "authority": 4,
                "rerank_score": 2.8,
            }
        ]
    else:
        results = [
            {
                "title": f"{query} · 搜索结果",
                "url": "https://example.com/search/result",
                "snippet": "这是一条用于联调工具结果表格的 Mock 搜索结果。",
                "summary": "Mock 搜索返回的摘要，用于验证引用、工具结果表格和展开面板。",
                "site_name": "Example",
                "date": "2026-10-29T00:00:00+00:00",
                "authority": 2,
                "rerank_score": 1.8,
            }
        ]
    return {"query": query, "results": results[:limit], "total": len(results[:limit])}


def mock_fetch_url(url: str) -> dict[str, object]:
    return {
        "url": url,
        "title": "Mock 网页正文",
        "content": "# Mock 网页正文\n\n这是用于验证 fetch_url 工具的示例正文。",
    }


def mock_web_search_tools(_settings: object) -> list[Tool]:
    return [Tool(mock_web_search, name="web_search"), Tool(mock_fetch_url, name="fetch_url")]


run_service.web_search_tools = mock_web_search_tools


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

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

        def write_config(path: str, content: str) -> str:
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

        async def run_command(command: str, timeout_seconds: int = 120) -> dict[str, object]:
            """在沙箱里跑一条 Linux 命令，返回 stdout/stderr/exit_code。

            mock 关掉了真沙箱（SANDBOX_API_KEY 被清空），这条假工具让「沙箱执行」有东西可看，
            返回形状与 `SandboxWorkspace.run_command` 一致。
            """
            await asyncio.sleep(0.8)
            return {"exit_code": 0, "stdout": _sandbox_output(command), "stderr": ""}

        return [
            *super().default_tools(),
            Tool(delete_file, name="delete_file", requires_approval=True),
            Tool(write_config, name="write_config", requires_approval=True),
            Tool(archive_log, name="archive_log", requires_approval=True),
            Tool(fetch_price_a, name="fetch_price_a"),
            Tool(fetch_price_b, name="fetch_price_b"),
            Tool(fetch_weather, name="fetch_weather"),
            Tool(lookup_order, name="lookup_order"),
            Tool(make_chart, name="make_chart"),
            Tool(run_command, name="run_command"),
        ]


APPROVAL_CALLS = [
    (
        "delete_file",
        lambda: {"path": random.choice(["tmp/cache.log", "dist/old.js", "tmp/upload.tmp"])},
    ),
    (
        "write_config",
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


async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    text = _last_user_text(messages)
    if "请压缩以上对话历史" in text:
        # 压缩是开跑前的独立请求；留一点延迟让前端能看到“压缩开始”的进行态
        await asyncio.sleep(1.2)
        return ModelResponse(parts=[TextPart(MOCK_COMPACTION_SUMMARY)])
    if "测试" in text:
        # 非流式请求走这里：思维链一次给全，正文与流式分支同一份
        return ModelResponse(parts=[ThinkingPart("\n".join(TEST_CHAIN)), TextPart(_test_report())])
    if "长文" in text:
        reply = _long_text()
    elif "代码" in text:
        reply = (
            "```python\n"
            + "\n".join(
                f"print('mock line {index}: {random.randint(1, 999)}')" for index in range(1, 6)
            )
            + "\n```"
        )
    else:
        reply = _random_text()
    return ModelResponse(parts=[TextPart(reply)])


def _preview_html() -> str:
    color = f"#{random.randint(0, 0xFFFFFF):06x}"
    return (
        "<style>body{font:14px/1.6 system-ui;margin:24px}"
        f"b{{color:{color}}}</style>"
        "<h3>Mock 预览</h3>"
        f"<p>主色 <b>{color}</b>，随机数 {random.randint(10, 99)}。</p>"
        '<button onclick="this.textContent+=1">点我 +1</button>'
    )


TEST_CHAIN: tuple[str, ...] = (
    "先把这条验收拆成可核对的四件事：思维链本身、联网搜索、沙箱执行、UI 预览。",
    "再加一段长代码块，看 markdown 渲染在高亮和展开上都还站得住。",
    "思维链要能持续流式输出，说明 `ThinkingPart` 的增量没有被前端截断，",
    "也没有在工具调用开始的那一刻被丢掉——这两件事以前都真的坏过。",
    "联网搜索要看两处：工具卡展开后参数与结果都在，以及回答里的引用能对上号。",
    "`web_search` 的 mock 结果固定返回 title / url / snippet / summary，",
    "外加 site_name / date / authority / rerank_score，",
    "所以引用行应该显示站点名，而不是把裸 URL 摊在读者脸上。",
    "沙箱执行要确认返回形状是 `exit_code` / `stdout` / `stderr`，",
    "退出码 0 时不该出现红色错误态；命令文本较长时卡片要换行而不是横向溢出。",
    "`pytest -q` 的输出有 145 行汇总，属于中等长度 stdout，",
    "正好检验展开区的高度上限与内部滚动。",
    "UI 预览走前端声明工具：调用后只应追加一个 HTML Tab，",
    "不该在正文里再插一张中间确认卡。",
    "预览内容要包含表格、按钮和一段脚本，",
    "用来验证 `allow-scripts` 的 iframe 里 JS 能跑、但拿不到同源能力。",
    "长代码块要覆盖三点：语法高亮、浅色主题下不糊、",
    "以及「展开」把源码写进独立 Tab 而不是复用 HTML Tab。",
    "Python 代码块故意留 40 多行并带中文注释，",
    "这样行高、等宽字体和横向滚动能一起看到。",
    "还要顺手确认这一轮没有审批卡、没有提问卡：",
    "三类中断里只留工具自动回填，面板不该弹出来挡输入框。",
    "如果这几步都过了，剩下就是看整体节奏：",
    "工具卡按发生顺序排列，思维链在它们之上，",
    "最后的正文回答不被撑开的卡片顶掉。",
    "结论：按 搜索 → 沙箱 → 预览 → 正文 的顺序发，一轮里三种工具各一次，",
    "最后用一段带代码块和表格的总结收尾。",
)


def _test_call(name: str) -> DeltaToolCall:
    """测试场景里的一次工具调用：参数固定，方便逐项核对渲染。"""
    if name == "web_search":
        args: dict[str, object] = {"query": "PigeonAgent 沙箱执行 与 联网搜索 验收", "count": 4}
    elif name == "run_command":
        args = {"command": "pytest -q", "timeout_seconds": 120}
    else:
        args = {"title": "Mock 验收看板", "html": _test_html()}
    return DeltaToolCall(
        name=name,
        json_args=json.dumps(args, ensure_ascii=False),
        tool_call_id=f"call_test_{uuid4().hex[:8]}",
    )


TEST_STEPS = ("web_search", "run_command", "ui_open_html_preview")


def _sandbox_output(command: str) -> str:
    """假沙箱输出：按命令关键字给一段看着像真的 stdout。"""
    if "pytest" in command:
        return (
            "============================= test session starts =============================\n"
            "platform win32 -- Python 3.12.7, pytest-8.3.4, pluggy-1.5.0\n"
            "collected 145 items\n\n"
            "tests\\test_agents.py ..........................                          [ 17%]\n"
            "tests\\test_api.py ....................................                   [ 42%]\n"
            "tests\\test_services.py ........................................          [ 70%]\n"
            "tests\\test_storage.py ...................................                [100%]\n\n"
            "============================= 145 passed in 18.42s =============================\n"
        )
    if "python" in command or "print" in command:
        return "hello from sandbox\nsum=4950 count=100\n"
    if "ls" in command:
        return "app\nfrontend\nmigrations\npyproject.toml\nREADME.md\nuv.lock\n"
    return f"$ {command}\n( mock 沙箱：命令未真实执行 )\n"


def _test_html() -> str:
    """预览 Tab 的内容：表格 + 交互按钮，验证 iframe 沙箱里的脚本能跑。"""
    return """<style>
  body {
    font: 14px/1.6 system-ui, -apple-system, "PingFang SC", sans-serif;
    margin: 24px;
    color: #0d0d0d;
  }
  h2 { font-size: 17px; margin: 0 0 4px; letter-spacing: -0.01em; }
  p.sub { margin: 0 0 18px; color: #767676; font-size: 12.5px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e5e5; }
  th { color: #767676; font-weight: 500; }
  td.ok { color: #3F6FA0; font-weight: 550; }
  button {
    margin-top: 16px;
    padding: 7px 14px;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
    background: #fff;
    font: inherit;
    cursor: pointer;
  }
  button:hover { background: #f7f7f8; }
</style>
<h2>Mock 验收看板</h2>
<p class="sub">这段 HTML 跑在 allow-scripts 的 iframe 里：脚本可执行，但拿不到同源能力。</p>
<table>
  <tr><th>能力</th><th>入口</th><th>结果</th></tr>
  <tr><td>思维链</td><td>ThinkingPart 增量</td><td class="ok">流式可见</td></tr>
  <tr><td>联网搜索</td><td>web_search</td><td class="ok">4 条结果</td></tr>
  <tr><td>沙箱执行</td><td>run_command</td><td class="ok">exit 0</td></tr>
  <tr><td>长代码块</td><td>markdown fence</td><td class="ok">高亮 + 展开</td></tr>
  <tr><td>UI 预览</td><td>ui_open_html_preview</td><td class="ok">本 Tab</td></tr>
</table>
<button onclick="window.n = (window.n || 0) + 1; this.textContent = '已点击 ' + window.n + ' 次'">
  点我 +1
</button>
"""


def _test_report() -> str:
    """收尾正文：长代码块 + 表格 + 引用，覆盖 markdown 渲染的主要形状。"""
    return """这一轮把五类渲染都跑了一遍，结论如下。

- **思维链**：本轮在调用 `web_search` 之前先流式输出了 13 段推理，工具卡与思维链共用同一逻辑轮次。
- **联网搜索**：`web_search` 返回 4 条结果，站点名与时间都进了引用行；
  参数与输出在卡片展开步骤里，不另开结果表格。
- **沙箱执行**：`run_command` 跑 `pytest -q`，`exit_code=0`，stdout 145 行汇总在展开区内部滚动。
- **UI 展示**：`ui_open_html_preview` 只追加了一个 HTML Tab，正文没有中间确认卡。

下面是长代码块，用来验高亮、行高、浅色主题与「展开」写入源码 Tab：

```python
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field


@dataclass(slots=True)
class Step:
    \"\"\"一条验收步骤：名字、执行体和期望耗时上限。\"\"\"

    name: str
    body: Callable[[], Awaitable[bool]]
    budget_seconds: float = 2.0
    started_at: float = field(default=0.0, init=False)

    async def run(self) -> tuple[str, bool, float]:
        self.started_at = time.perf_counter()
        try:
            ok = await asyncio.wait_for(self.body(), timeout=self.budget_seconds)
        except TimeoutError:
            ok = False
        return self.name, ok, time.perf_counter() - self.started_at


async def collect(steps: Iterable[Step]) -> list[tuple[str, bool, float]]:
    \"\"\"并发跑完所有步骤，按提交顺序返回结果，方便和正文里的列表对齐。\"\"\"
    pending = [asyncio.create_task(step.run()) for step in steps]
    results: list[tuple[str, bool, float]] = []
    for task in asyncio.as_completed(pending):
        name, ok, elapsed = await task
        # 慢步骤单独打日志，验收时能一眼看出是哪一类渲染拖了时间
        if elapsed > 0.8:
            print(f"slow step: {name} took {elapsed:.2f}s")
        results.append((name, ok, elapsed))
    return sorted(results, key=lambda item: item[0])


def summarize(results: list[tuple[str, bool, float]]) -> str:
    passed = sum(1 for _, ok, _ in results if ok)
    lines = [f"{name}: {'ok' if ok else 'fail'} ({elapsed:.2f}s)" for name, ok, elapsed in results]
    return "\\n".join([f"{passed}/{len(results)} 通过", *lines])
```

| 能力 | 载体 | 观察点 |
| --- | --- | --- |
| 思维链 | `ThinkingPart` | 分段流式、不被工具卡顶掉 |
| 联网搜索 | `web_search` | 引用行显示站点名 |
| 沙箱执行 | `run_command` | exit 0 不显错误态 |
| 长代码块 | markdown fence | 高亮 + 展开成 Tab |
| UI 展示 | `ui_open_html_preview` | 只追加 Tab，无中间卡 |

引用：示例天气 · Spring 官方文档 · Pydantic AI 事件流说明 · Mock 网页正文（全部来自 mock 假数据）。
"""


async def respond_stream(messages: list[ModelMessage], _info: AgentInfo):
    text = _last_user_text(messages)
    tool_names = {tool.name for tool in _info.function_tools}
    if "测试" in text:
        done = {part.tool_name for part in _round_returns(messages)}
        # 开关没开就没有 web_search，本地工作区也没有真沙箱：按实际挂载的工具走，别硬调
        steps = [name for name in TEST_STEPS if name in tool_names]
        next_step = next((name for name in steps if name not in done), None)
        if next_step is not None:
            if not done:
                # 思维链占 part 0，工具调用必须另起序号：同一个 index 复用会被
                # parts manager 判成「往 ThinkingPart 上打工具增量」而直接报错
                for chunk in TEST_CHAIN:
                    await asyncio.sleep(0.35)
                    yield {0: DeltaThinkingPart(content=chunk)}
            yield {1: _test_call(next_step)}
            return
        for char in _test_report():
            await asyncio.sleep(0.004)
            yield char
        return
    can_search = not _has_tool_result(messages) and "web_search" in tool_names
    if can_search and ("搜索" in text or "天气" in text):
        yield {
            0: DeltaToolCall(
                name="web_search",
                json_args=json.dumps(
                    {"query": text[:128], "count": 3},
                    ensure_ascii=False,
                ),
                tool_call_id=f"call_search_{uuid4().hex[:8]}",
            )
        }
        return
    if "报错" in text:
        yield "半截回答："
        raise RuntimeError("Mock 模型故意报错")

    if _has_tool_result(messages):
        conclusion = random.choice(["继续", "重试", "观察"])
        reply = random.choice(
            [
                f"工具结果已回填 #{uuid4().hex[:4]}：已完成当前操作。",
                f"外部结果收到了 #{uuid4().hex[:4]}，随机结论是 {conclusion}。",
            ]
        )
    elif "长文" in text:
        reply = _long_text()
    elif "代码" in text:
        reply = (
            "```python\n"
            + "\n".join(
                f"print('mock line {index}: {random.randint(1, 999)}')" for index in range(1, 6)
            )
            + "\n```"
        )
    else:
        reply = _random_text()

    slow = "超慢" in text
    medium = "慢速" in text
    forced_text = slow or medium or "长文" in text or "代码" in text
    # 一批里同时给审批和外部回填两种卡：面板要一页一项，不叠在一起
    if "混合卡片" in text and _returned(messages, "delete_file") == 0:
        yield {
            0: DeltaToolCall(
                name="delete_file",
                json_args=json.dumps({"path": "tmp/cache.log"}),
                tool_call_id=f"call_approval_{uuid4().hex[:8]}",
            ),
            1: DeltaToolCall(
                name="fetch_price_a",
                json_args=json.dumps({"symbol": "BTC"}),
                tool_call_id=f"call_external_{uuid4().hex[:8]}",
            ),
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
    context_window=MOCK_CONTEXT_WINDOW or None,
    supports_tools=True,
)
ModelFactory.create = lambda self, record: resolved
run_service.BaseAgent = MockAgent

import uvicorn
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection

from app.core import security
from app.db import Base
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.account.user import User
from app.models.ai.llm import LlmModel

MOCK_MODEL_NAME = "Mock Agent"
# mock 的默认测试账号：省掉注册 + 邮箱验证码这一步
MOCK_ADMIN_EMAIL = "admin@example.com"
MOCK_ADMIN_PASSWORD = "admin12345"


def _ensure_session_run_columns(connection: Connection) -> None:
    """create_all 不会给老表补列；mock 库跨版本复用，这里手动跟上新字段。"""
    columns = {column["name"] for column in inspect(connection).get_columns("session_runs")}
    if "compacted" not in columns:
        connection.execute(
            text("ALTER TABLE session_runs ADD COLUMN compacted BOOLEAN NOT NULL DEFAULT 0")
        )


def _ensure_session_columns(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("sessions")}
    if "pending_batches" not in columns:
        connection.execute(
            text("ALTER TABLE sessions ADD COLUMN pending_batches INTEGER NOT NULL DEFAULT 0")
        )


def _ensure_user_columns(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("users")}
    if "preferences" not in columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN preferences JSON NOT NULL DEFAULT '{}'")
        )
    if "email_verified" not in columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1")
        )
    if "token_version" not in columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
        )
    if "avatar_file_id" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN avatar_file_id CHAR(32)"))


async def _ensure_mock_schema() -> None:
    """补齐新增表 / 新列：mock 库是长期复用的，不能只靠首次 seed。"""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_session_run_columns)
        await connection.run_sync(_ensure_session_columns)
        await connection.run_sync(_ensure_user_columns)


async def _ensure_mock_admin() -> None:
    """钉死一个能登录、且是管理员的账号。

    每次启动都重写密码并补 is_admin：库里已经有同名账号（比如手滑注册过）也照样能进。
    """
    digest = await asyncio.to_thread(security.hash_password, MOCK_ADMIN_PASSWORD)
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == MOCK_ADMIN_EMAIL))
        if user is None:
            db.add(
                User(
                    email=MOCK_ADMIN_EMAIL,
                    password_hash=digest,
                    display_name="Mock 管理员",
                    is_admin=True,
                    is_active=True,
                )
            )
        else:
            user.password_hash = digest
            user.is_admin = True
            user.is_active = True
        await db.commit()
        print(f"mock admin ready: {MOCK_ADMIN_EMAIL} / {MOCK_ADMIN_PASSWORD}", flush=True)


async def _ensure_mock_model() -> None:
    """启动时确保 mock 模型存在：前端靠模型列表才能发起会话。

    模型全局共享，推理早已被 FunctionModel 接管，这条记录只决定可选列表和默认项。
    """
    # 管理员的种子任务是并发起的，等它有用户落库再写模型；库里本来就有人时立刻返回
    for _ in range(50):
        async with async_session_factory() as db:
            user = await db.scalar(select(User).order_by(User.created_at).limit(1))
        if user is not None:
            break
        await asyncio.sleep(0.1)
    else:
        print("mock model skipped: no user in database", flush=True)
        return

    async with async_session_factory() as db:
        model = await db.scalar(select(LlmModel).where(LlmModel.name == MOCK_MODEL_NAME))
        if model is None:
            has_default = await db.scalar(
                select(LlmModel.id).where(LlmModel.is_default.is_(True)).limit(1)
            )
            model = LlmModel(
                name=MOCK_MODEL_NAME,
                provider="openai",
                model_name="mock",
                context_window=MOCK_CONTEXT_WINDOW or None,
                supports_tools=True,
                is_active=True,
                is_default=has_default is None,
                thinking_levels=["low", "medium", "high"],
            )
            db.add(model)
        else:
            model.is_active = True
            model.context_window = MOCK_CONTEXT_WINDOW or None
            model.thinking_levels = ["low", "medium", "high"]
        await db.commit()
        print(f"mock model ready: id={model.id} name={model.name}", flush=True)


_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_mock_model(application: object):
    try:
        await _ensure_mock_schema()
    except Exception as error:
        print(f"mock schema skipped: {error!r}", flush=True)
    # 先进测试账号再跑原 lifespan：ensure_admin 见库里有人就会自己跳过
    try:
        await _ensure_mock_admin()
    except Exception as error:  # 表还没建好之类的问题不该拖垮 mock，登录不了再看日志
        print(f"mock admin skipped: {error!r}", flush=True)
    async with _original_lifespan(application):
        try:
            await _ensure_mock_model()
        except Exception as error:  # 注入失败不该把 mock 整体拖垮
            print(f"mock model skipped: {error!r}", flush=True)
        yield


app.router.lifespan_context = _lifespan_with_mock_model

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["MOCK_PORT"]),
    log_level="warning",
)
