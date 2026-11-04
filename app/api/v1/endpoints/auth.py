from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, RateLimiterDep, SessionDep, SettingsDep
from app.schemas.user import (
    ChangePasswordIn,
    EmailIn,
    LoginIn,
    MessageOut,
    ProfileUpdateIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    TokenPairOut,
    UserPreferencesUpdate,
    UserRead,
    VerifyIn,
)
from app.services import user as user_service
from app.services.user import normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])

# 认证入口是全服务最贵的公开接口：一次登录要跑一次 bcrypt cost 12（约 0.2s CPU），
# 一封验证码是一笔 SMTP 开销，而这两件事谁都调得到。按规范化邮箱开窗计数——
# 用邮箱而不是 IP，是因为服务在反向代理后面，来源地址要么全一样、要么取决于能否
# 信任 X-Forwarded-For；字典爆破针对的也正是"同一个账号"。
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 300.0
REGISTER_LIMIT = 5
REGISTER_WINDOW_SECONDS = 900.0
# 验证码本身错 5 次即废（CODE_MAX_ATTEMPTS），这里挡的是反复换码硬试
VERIFY_LIMIT = 10
VERIFY_WINDOW_SECONDS = 600.0
# 重发另有 60 秒冷却（resend_code），这条限的是换着时间点持续骚扰
RESEND_LIMIT = 6
RESEND_WINDOW_SECONDS = 3600.0


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    payload: RegisterIn,
) -> RegisterOut:
    key = f"register:{normalize_email(payload.email)}"
    await limiter.enforce("注册", key, REGISTER_LIMIT, REGISTER_WINDOW_SECONDS)
    user, tokens = await user_service.register(db, settings, payload)
    if tokens is None:
        return RegisterOut(verification_required=True)
    return RegisterOut(
        verification_required=False,
        user=UserRead.model_validate(user),
        tokens=tokens,
    )


@router.post("/verify", response_model=TokenPairOut)
async def verify(
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    payload: VerifyIn,
) -> TokenPairOut:
    key = f"verify:{normalize_email(payload.email)}"
    await limiter.enforce("验证", key, VERIFY_LIMIT, VERIFY_WINDOW_SECONDS)
    return await user_service.verify_email(db, settings, payload.email, payload.code)


@router.post("/resend", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
async def resend(
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    payload: EmailIn,
) -> MessageOut:
    key = f"resend:{normalize_email(payload.email)}"
    await limiter.enforce("重发验证码", key, RESEND_LIMIT, RESEND_WINDOW_SECONDS)
    # 统一文案，不让响应区分出该邮箱是否处于待验证状态
    await user_service.resend_code(db, settings, payload.email)
    return MessageOut(detail="若该邮箱处于待验证状态，验证码已重新发送")


@router.post("/login", response_model=TokenPairOut)
async def login(
    db: SessionDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    payload: LoginIn,
) -> TokenPairOut:
    key = f"login:{normalize_email(payload.email)}"
    await limiter.enforce("登录", key, LOGIN_LIMIT, LOGIN_WINDOW_SECONDS)
    return await user_service.login(db, settings, payload)


@router.post("/refresh", response_model=TokenPairOut)
async def refresh(db: SessionDep, settings: SettingsDep, payload: RefreshIn) -> TokenPairOut:
    return await user_service.refresh_tokens(db, settings, payload.refresh_token)


@router.post("/logout-all", response_model=MessageOut)
async def logout_all_devices(db: SessionDep, user: CurrentUserDep) -> MessageOut:
    """登出所有设备：本机退出只清本地令牌，这一条才作废已签发的 refresh。"""
    await user_service.logout_all_devices(db, user)
    return MessageOut(detail="已在所有设备登出")


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
async def update_me(payload: ProfileUpdateIn, db: SessionDep, user: CurrentUserDep) -> UserRead:
    updated = await user_service.update_profile(db, user, payload.model_dump(exclude_unset=True))
    return UserRead.model_validate(updated)


@router.patch("/me/preferences", response_model=UserRead)
async def update_preferences(
    payload: UserPreferencesUpdate, db: SessionDep, user: CurrentUserDep
) -> UserRead:
    updated = await user_service.update_preferences(db, user, payload)
    return UserRead.model_validate(updated)


@router.post("/me/password", response_model=TokenPairOut)
async def change_password(
    payload: ChangePasswordIn,
    db: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
) -> TokenPairOut:
    return await user_service.change_password(
        db,
        user,
        payload.current_password,
        payload.new_password,
        settings=settings,
    )
