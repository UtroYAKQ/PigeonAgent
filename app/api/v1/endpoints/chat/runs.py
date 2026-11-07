import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    CurrentUserDep,
    RenderHubDep,
    RunRegistryDep,
    SandboxPoolDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.core.exceptions import GoneError, UnprocessableError
from app.render.consumer import RenderConsumer
from app.render.queue import RenderCursorInvalid
from app.schemas.run import RunCreate, RunRead, RunResume
from app.services.chat import session as session_service
from app.services.run.launch import launch_run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["runs"])

# SSE 心跳间隔：工具长时间运行期间保持连接不被反代/客户端掐断
HEARTBEAT_INTERVAL_SECONDS = 15.0


@router.post(
    "/{session_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    session_id: UUID,
    payload: RunCreate,
    db: SessionDep,
    session_factory: SessionFactoryDep,
    hub: RenderHubDep,
    registry: RunRegistryDep,
    pool: SandboxPoolDep,
    user: CurrentUserDep,
    settings: SettingsDep,
) -> RunRead:
    run_id = await launch_run(
        db,
        session_id,
        payload,
        owner_id=user.id,
        session_factory=session_factory,
        hub=hub,
        registry=registry,
        sandbox_pool=pool,
        settings=settings,
    )
    return RunRead(run_id=run_id)


@router.post(
    "/{session_id}/runs/resume",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_run(
    session_id: UUID,
    payload: RunResume,
    db: SessionDep,
    session_factory: SessionFactoryDep,
    hub: RenderHubDep,
    registry: RunRegistryDep,
    pool: SandboxPoolDep,
    user: CurrentUserDep,
    settings: SettingsDep,
) -> RunRead:
    run_id = await launch_run(
        db,
        session_id,
        payload,
        owner_id=user.id,
        session_factory=session_factory,
        hub=hub,
        registry=registry,
        sandbox_pool=pool,
        settings=settings,
    )
    return RunRead(run_id=run_id)


@router.post(
    "/{session_id}/runs/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_run(
    session_id: UUID,
    run_id: str,
    db: SessionDep,
    registry: RunRegistryDep,
    user: CurrentUserDep,
) -> None:
    # 会话不属于调用者就当不存在，顺手防掉跨用户取消探测
    await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    await registry.cancel_run(session_id, run_id)


@router.get("/{session_id}/runs/{run_id}/events")
async def stream_run_events(
    session_id: UUID,
    run_id: str,
    hub: RenderHubDep,
    request: Request,
    db: SessionDep,
    user: CurrentUserDep,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            after = int(last_event_id)
        except ValueError as exc:
            raise UnprocessableError("Last-Event-ID 必须是整数") from exc

    try:
        consumer = await hub.subscribe(run_id, after, session_id=session_id)
    except RenderCursorInvalid as exc:
        raise UnprocessableError(str(exc)) from exc
    if consumer is None:
        raise GoneError(f"Run {run_id} is not streaming")

    return StreamingResponse(
        _encode(consumer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _encode(consumer: RenderConsumer) -> AsyncIterator[str]:
    try:
        while True:
            try:
                async with asyncio.timeout(HEARTBEAT_INTERVAL_SECONDS):
                    events, closed = await consumer.read()
            except TimeoutError:
                yield ": ping\n\n"
                continue
            for item in events:
                yield f"id: {item.seq}\ndata: {item.event.model_dump_json(by_alias=True)}\n\n"
            if closed:
                return
    finally:
        # 消费者退出后队列才知道落盘文件可以回收了
        consumer.close()
