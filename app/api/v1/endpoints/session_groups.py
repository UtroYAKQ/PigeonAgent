from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, SessionDep
from app.models.session_group import SessionGroup
from app.schemas.session_group import GroupCreate, GroupList, GroupRead
from app.services import session_group as group_service

router = APIRouter(prefix="/groups", tags=["groups"])


def _read(group: SessionGroup, session_count: int) -> GroupRead:
    return GroupRead.model_validate(group).model_copy(update={"session_count": session_count})


@router.get("", response_model=GroupList)
async def list_groups(session: SessionDep, user: CurrentUserDep) -> GroupList:
    rows = await group_service.list_groups(session, owner_id=user.id)
    items = [_read(group, count) for group, count in rows]
    return GroupList(items=items, total=len(items))


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate, session: SessionDep, user: CurrentUserDep
) -> GroupRead:
    group = await group_service.create_group(session, payload, owner_id=user.id)
    return _read(group, await group_service.session_count(session, group.id, owner_id=user.id))


@router.patch("/{group_id}", response_model=GroupRead)
async def rename_group(
    group_id: int, payload: GroupCreate, session: SessionDep, user: CurrentUserDep
) -> GroupRead:
    group = await group_service.rename_group(session, group_id, payload, owner_id=user.id)
    return _read(group, await group_service.session_count(session, group.id, owner_id=user.id))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int, session: SessionDep, user: CurrentUserDep
) -> None:
    await group_service.delete_group(session, group_id, owner_id=user.id)
