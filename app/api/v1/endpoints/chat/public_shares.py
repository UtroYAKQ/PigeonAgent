import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import RateLimiterDep, SessionDep
from app.schemas.chat.shares import SharedConversationRead, SharedSessionRead
from app.schemas.run import SessionRunRead
from app.services.chat import shares as share_service
from app.services.run import path_runs

router = APIRouter(prefix="/public/shares", tags=["public"])

TokenParam = Annotated[str, Path(min_length=32, max_length=64, description="链接口令")]

# 一次给足：分享页不需要像工作区那样精细分页，超出这一页再靠 before_run_id 往前翻
PAGE_SIZE = 200
# 读取一次就写一次访问计数，所以这条公开路由也要限流，别让人拿一个链接把库打满
READ_LIMIT = 120
READ_WINDOW_SECONDS = 60.0


@router.get("/{token}", response_model=SharedConversationRead)
async def read_share(
    token: TokenParam,
    db: SessionDep,
    limiter: RateLimiterDep,
    before_run_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SharedConversationRead:
    """匿名读取一段会话：只给标题、时间与正文条目，分支切换等写能力一概不给。"""
    await limiter.enforce("打开分享链接", f"share:{token}", READ_LIMIT, READ_WINDOW_SECONDS)
    share, chat_session = await share_service.resolve_share(db, token)
    runs, has_more = await path_runs(
        db, chat_session.id, before_run_id=before_run_id, limit=PAGE_SIZE
    )
    return SharedConversationRead(
        session=SharedSessionRead(
            title=chat_session.title,
            created_at=chat_session.created_at,
            last_run_at=chat_session.last_run_at,
        ),
        runs=[SessionRunRead.model_validate(run) for run in runs],
        has_more=has_more,
        expires_at=share.expires_at,
    )
