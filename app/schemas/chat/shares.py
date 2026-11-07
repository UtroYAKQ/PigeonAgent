"""会话分享：创建参数、主人视角的列表项、访客视角的正文。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.run import SessionRunRead


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    # 创建时就要给到期日，上限一年：不让"临时分享"悄悄变成永久公开面
    expires_in_days: int = Field(default=7, ge=1, le=365)


class ShareRead(BaseModel):
    """主人视角。口令只在创建与列表里出现，链接由前端按当前站点拼出来。"""

    id: uuid.UUID
    session_id: uuid.UUID
    session_title: str | None
    token: str
    expires_at: datetime
    visit_count: int
    last_visited_at: datetime | None
    created_at: datetime


class SharedSessionRead(BaseModel):
    """访客只需要认得出这是哪段对话；内部状态一概不下发。"""

    title: str | None
    created_at: datetime
    last_run_at: datetime


class SharedConversationRead(BaseModel):
    session: SharedSessionRead
    runs: list[SessionRunRead]
    has_more: bool
    expires_at: datetime
