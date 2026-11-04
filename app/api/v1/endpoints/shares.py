import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import CurrentUserDep, EnvSettingsDep, SessionDep
from app.schemas.session_share import ShareCreate, ShareRead
from app.services import chat_session as session_service
from app.services import session_share as share_service

router = APIRouter(prefix="/shares", tags=["shares"])

ShareIdPath = Annotated[uuid.UUID, Path(description="分享链接 id")]


@router.post("", response_model=ShareRead, status_code=status.HTTP_201_CREATED)
async def create_share(
    payload: ShareCreate,
    db: SessionDep,
    user: CurrentUserDep,
    settings: EnvSettingsDep,
) -> ShareRead:
    """为一段会话签发只读链接；owner 取自令牌，别人会话的 id 一律 404。"""
    chat_session = await session_service.get_session_or_404(
        db, payload.session_id, owner_id=user.id
    )
    return await share_service.create_share(
        db, settings, session=chat_session, expires_in_days=payload.expires_in_days
    )


@router.get("", response_model=list[ShareRead])
async def list_shares(
    db: SessionDep, user: CurrentUserDep, settings: EnvSettingsDep
) -> list[ShareRead]:
    """我这个账号发出去、还没到期的链接。"""
    return await share_service.list_shares(db, settings, owner_id=user.id)


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(share_id: ShareIdPath, db: SessionDep, user: CurrentUserDep) -> Response:
    await share_service.revoke_share(db, share_id=share_id, owner_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
