
from fastapi import APIRouter, status
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.schemas.user import (
    Email,
    LoginIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    TokenPairOut,
    UserRead,
    VerifyIn,
)
from app.services import user as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class MessageOut(BaseModel):
    detail: str


class EmailIn(BaseModel):
    email: Email


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(db: SessionDep, settings: SettingsDep, payload: RegisterIn) -> RegisterOut:
    user, tokens = await user_service.register(db, settings, payload)
    if tokens is None:
        return RegisterOut(verification_required=True)
    return RegisterOut(
        verification_required=False,
        user=UserRead.model_validate(user),
        tokens=tokens,
    )


@router.post("/verify", response_model=TokenPairOut)
async def verify(db: SessionDep, settings: SettingsDep, payload: VerifyIn) -> TokenPairOut:
    return await user_service.verify_email(db, settings, payload.email, payload.code)


@router.post("/resend", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
async def resend(db: SessionDep, settings: SettingsDep, payload: EmailIn) -> MessageOut:
    # 统一文案，不让响应区分出该邮箱是否处于待验证状态
    await user_service.resend_code(db, settings, payload.email)
    return MessageOut(detail="若该邮箱处于待验证状态，验证码已重新发送")


@router.post("/login", response_model=TokenPairOut)
async def login(db: SessionDep, settings: SettingsDep, payload: LoginIn) -> TokenPairOut:
    return await user_service.login(db, settings, payload)


@router.post("/refresh", response_model=TokenPairOut)
async def refresh(db: SessionDep, settings: SettingsDep, payload: RefreshIn) -> TokenPairOut:
    return await user_service.refresh_tokens(db, settings, payload.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)
