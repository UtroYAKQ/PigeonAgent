"""Randomized demo seed for the mock UI environment."""

import asyncio
import base64
import random
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.enums import RunKind, RunStatus
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    CustomItem,
    FileItem,
    TextItem,
    TokenUsage,
    ToolCallItem,
)
from app.services import item_codec
from app.services import chat_session as session_service
from app.schemas.session import SessionCreate

APPROVALS = [
    ("delete_file", lambda: {"path": random.choice(["tmp/cache.log", "dist/old.js", "tmp/upload.tmp"])}),
    (
        "write_file",
        lambda: {
            "path": random.choice(["src/config.py", "README.md", "app/settings.py"]),
            "content": f"# seeded by mock #{uuid4().hex[:4]}\n",
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

CALLS = [
    ("fetch_price_a", lambda: {"symbol": random.choice(["AAA", "BTC", "ETH"])}),
    ("fetch_price_b", lambda: {"symbol": random.choice(["BBB", "SOL", "DOGE"])}),
    ("fetch_weather", lambda: {"city": random.choice(["上海", "东京", "柏林"])}),
    ("lookup_order", lambda: {"order_id": f"ORD-{random.randint(1000, 9999)}"}),
]

TEXTS = [
    "先检查了缓存目录，发现两个过期文件，准备清理。",
    "随机选了一个分支做对比，差异主要集中在错误处理和日志字段。",
    "我把结果整理成三点：影响范围、复现条件、下一步动作。",
]


def _tools(picks: list[tuple[str, dict]]) -> list[ToolCallItem]:
    return [
        ToolCallItem(
            tool_call_id=f"call_{uuid4().hex[:8]}",
            tool_name=name,
            args=args,
        )
        for name, args in picks
    ]


def _reply() -> str:
    tag = uuid4().hex[:4]
    return random.choice(
        [
            f"Mock 回应 #{tag}：已完成当前操作。",
            f"随机结论 #{tag}：命中 {random.randint(1, 9)} 条规则，建议继续观察。",
            f"## 随机报告 #{tag}\n\n- 检查项 A\n- 检查项 B\n\n```python\nprint('{tag}')\n```",
        ]
    )


async def main() -> None:
    sqlite_path = "pigeon_mock.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///./{sqlite_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        model = LlmModel(
            name="Mock Agent",
            provider="openai",
            model_name="mock",
            supports_tools=True,
            is_active=True,
            is_default=True,
        )
        db.add(model)
        await db.flush()
        tag = uuid4().hex[:4]
        chat = await session_service.create_session(
            db, SessionCreate(title=f"随机 Mock #{tag}", model_id=model.id)
        )
        now = datetime.now(UTC)
        usage = TokenUsage(requests=3, input_tokens=random.randint(9000, 18000), output_tokens=1800)

        approval_picks = [
            (name, factory()) for name, factory in random.sample(APPROVALS, random.randint(1, 3))
        ]
        approval_calls = _tools(approval_picks)
        approval_run = SessionRun(
            id=uuid4(),
            session_id=chat.id,
            parent_run_id=None,
            seq=1,
            status=RunStatus.INTERRUPTED.value,
            kind=RunKind.TURN.value,
            model_id=model.id,
            usage=usage,
            content=[
                TextItem(role="user", text=f"随机触发一次审批 #{tag}，先看参数。"),
                TextItem(role="assistant", text=random.choice(TEXTS)),
                *approval_calls,
                ApprovalRequestItem(
                    interrupt_id=uuid4(),
                    tool_call_ids=[call.tool_call_id for call in approval_calls],
                ),
                CustomItem(
                    renderer="status-card",
                    data={
                        "title": f"随机审查 #{tag}",
                        "rows": [
                            ["缓存", random.choice(["已完成", "进行中", "待确认"])],
                            ["日志", random.choice(["已完成", "进行中", "待确认"])],
                            ["配置", random.choice(["已完成", "进行中", "待确认"])],
                        ],
                    },
                ),
            ],
        )

        call_picks = [
            (name, factory()) for name, factory in random.sample(CALLS, random.randint(1, 3))
        ]
        external_calls = _tools(call_picks)
        call_run = SessionRun(
            id=uuid4(),
            session_id=chat.id,
            parent_run_id=None,
            seq=2,
            status=RunStatus.INTERRUPTED.value,
            kind=RunKind.TURN.value,
            model_id=model.id,
            usage=usage,
            content=[
                TextItem(role="user", text=f"随机查询外部数据 #{tag}。"),
                TextItem(role="assistant", text="这些查询需要外部系统执行，我先把请求发出去。"),
                *external_calls,
                CallRequestItem(
                    interrupt_id=uuid4(),
                    tool_call_ids=[call.tool_call_id for call in external_calls],
                    metadata={
                        call.tool_call_id: {"source": "mock-vendor"} for call in external_calls
                    },
                ),
            ],
        )

        file_content = base64.b64encode(f"随机附件内容 #{tag}\n".encode()).decode()
        file_run = SessionRun(
            id=uuid4(),
            session_id=chat.id,
            parent_run_id=None,
            seq=3,
            status=RunStatus.COMPLETED.value,
            kind=RunKind.TURN.value,
            model_id=model.id,
            usage=usage,
            content=[
                TextItem(role="user", text=f"看看这个随机附件 #{tag}。"),
                FileItem(
                    role="user",
                    name=f"random-{tag}.txt",
                    media_type="text/plain",
                    data=file_content,
                    size=len(base64.b64decode(file_content)),
                ),
                TextItem(role="assistant", text=_reply()),
            ],
        )

        for run in (approval_run, call_run, file_run):
            run.preview = item_codec.preview_of(run.content)
            run.updated_at = now

        db.add_all([approval_run, call_run, file_run])
        chat.run_seq = 3
        chat.active_leaf_run_id = approval_run.id
        chat.last_run_at = now
        await db.commit()
        print(f"mock db ready: session={chat.id} leaf={approval_run.id} title={chat.title}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
