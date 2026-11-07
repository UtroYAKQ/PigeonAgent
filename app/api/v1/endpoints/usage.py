"""个人用量：余额、按天、按模型、最近对话。"""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.schemas.billing.usage import UsageOverview
from app.services.billing import usage as usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/me", response_model=UsageOverview)
async def my_usage(
    session: SessionDep,
    user: CurrentUserDep,
    settings: SettingsDep,
) -> UsageOverview:
    return await usage_service.overview(session, user=user, settings=settings)
