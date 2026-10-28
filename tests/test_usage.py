"""token 用量随 run 保存：一次模型响应至少记一次请求，汇总按字段累加。"""

from collections.abc import AsyncIterator
from uuid import UUID

from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.schemas.run_item import TokenUsage
from app.services import session_run as run_service
from tests.helpers import all_runs


async def stream_text(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
    yield "你好"


async def test_usage_is_persisted_on_runs(client: AsyncClient, db_session: AsyncSession) -> None:
    created = await client.post("/api/v1/sessions", json={"title": "usage"})
    session_id = UUID(created.json()["id"])
    agent = BaseAgent(
        FunctionModel(stream_function=stream_text),
        session=db_session,
        session_id=session_id,
    )

    await agent.run("第一轮")
    await agent.run("第二轮")

    runs = await all_runs(db_session, session_id)
    assert len(runs) == 2
    assert all(run.usage.requests == 1 for run in runs)
    assert all(run.usage.input_tokens > 0 for run in runs)

    summary = await run_service.usage_summary(db_session, session_id)
    assert summary.requests == 2
    assert summary.input_tokens > 0


def test_token_usage_only_keeps_aggregatable_fields() -> None:
    """provider 的原始键不入库：merged() 按固定字段表累加，多存的键会被静默丢掉。"""
    usage = TokenUsage.model_validate(
        {"input_tokens": 5, "output_tokens": 2, "cost": 0.2, "details": {"x": 1}}
    )
    assert "cost" not in usage.model_dump()
    assert usage.total_tokens == 7

    total = usage.merged(TokenUsage.model_validate({"input_tokens": 7, "requests": 1}))
    assert total.input_tokens == 12
    assert total.output_tokens == 2
    assert total.requests == 1
    assert total.total_tokens == 14
