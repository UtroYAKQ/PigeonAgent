"""积分计费：换算、幂等结算、余额拦截、图片计费、run 期间的用量守卫。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.store import SessionStore
from app.core.config import Settings
from app.core.exceptions import AppError, CreditsExhausted, NotFoundError
from app.domain.run_items import TokenUsage
from app.enums import RunStatus
from app.models.credit_ledger import CHAT, CreditLedger
from app.models.image_model import ImageModel
from app.models.llm_model import LlmModel
from app.models.session_run import SessionRun
from app.models.user import User
from app.services import billing, credit_guard
from app.services import run_store as run_store
from tests.conftest import TEST_SECRET_KEY, TEST_USER_ID, ensure_test_user
from tests.helpers import make_session


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "secret_key": TEST_SECRET_KEY,
        "sandbox_api_key": None,
        "billing_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def _user(db: AsyncSession) -> User:
    user = await ensure_test_user(db)
    user.credits_balance = 100
    await db.commit()
    return user


async def _make_run(
    db: AsyncSession, session_id: Any, usage: TokenUsage, *, model_id: int | None = None
) -> SessionRun:
    run = await run_store.create_run(
        db, session_id, run_id=uuid4(), content=[], status=RunStatus.COMPLETED
    )
    run.usage = usage
    run.model_id = model_id
    await db.commit()
    await db.refresh(run)
    return run


def _model(db: AsyncSession, **overrides: Any) -> LlmModel:
    fields: dict[str, Any] = {
        "name": f"m-{uuid4().hex[:8]}",
        "provider": "openai",
        "model_name": "gpt-test",
    }
    fields.update(overrides)
    return LlmModel(**fields)


# --------------------------------------------------------------------- 换算


def test_price_tokens_is_strictly_linear() -> None:
    rate = billing.TokenRate(input_per_1m=2.0, output_per_1m=8.0)
    # 1.5M 输入 = 3 分，0.5M 输出 = 4 分
    usage = TokenUsage(input_tokens=1_500_000, output_tokens=500_000)
    assert billing.price_tokens(usage, rate) == 7.0
    # 小用量严格线性：1.694M‰×2 + 0.239M‰×8 = 0.0053 分，不许"最少扣 1 分"放大
    tiny = TokenUsage(input_tokens=1_694, output_tokens=239)
    assert billing.price_tokens(tiny, rate) == pytest.approx(0.0053, abs=1e-6)
    # 零用量不扣
    assert billing.price_tokens(TokenUsage(), rate) == 0.0


def test_price_tokens_bills_cache_hits_at_cache_rate() -> None:
    rate = billing.TokenRate(input_per_1m=2.0, output_per_1m=8.0, cache_read_per_1m=0.5)
    # 1M 输入里 800K 命中缓存：普通输入 0.4 + 缓存 0.4
    usage = TokenUsage(input_tokens=1_000_000, cache_read_tokens=800_000)
    assert billing.price_tokens(usage, rate) == pytest.approx(0.8)

    # 没配缓存价就按输入价，和旧口径一致
    fallback = billing.TokenRate(input_per_1m=2.0, output_per_1m=8.0)
    assert billing.price_tokens(usage, fallback) == pytest.approx(2.0)

    # 缓存数不会超过输入数，避免把普通输入扣成负数
    tiny = TokenUsage(input_tokens=1_000, cache_read_tokens=5_000_000)
    assert billing.price_tokens(tiny, rate) == pytest.approx(0.0005)


def test_price_images() -> None:
    assert billing.price_images(3, 20.0) == 60
    assert billing.price_images(0, 20.0) == 0
    assert billing.price_images(3, 0.0) == 0


# --------------------------------------------------------------------- 结算


async def test_settle_run_applies_cache_rate(db_session: AsyncSession) -> None:
    await _user(db_session)
    session_id = await make_session(db_session)
    model = _model(
        db_session,
        credit_input_per_1m=2.0,
        credit_output_per_1m=8.0,
        credit_cache_read_per_1m=0.5,
    )
    db_session.add(model)
    await db_session.commit()
    run = await _make_run(
        db_session,
        session_id,
        TokenUsage(input_tokens=1_000_000, cache_read_tokens=800_000),
        model_id=model.id,
    )

    charged = await billing.settle_run(
        db_session, _settings(), session_id=session_id, run_id=run.id
    )

    # 普通输入 200K × 2 + 缓存 800K × 0.5，各按每 100 万折算
    assert charged == pytest.approx(0.8)


async def test_settle_run_charges_exactly_once(db_session: AsyncSession) -> None:
    await _user(db_session)
    session_id = await make_session(db_session)
    model = _model(db_session, credit_input_per_1m=2.0, credit_output_per_1m=8.0)
    db_session.add(model)
    await db_session.commit()
    run = await _make_run(
        db_session,
        session_id,
        TokenUsage(input_tokens=1_000_000, output_tokens=500_000),
        model_id=model.id,
    )
    settings = _settings()

    charged = await billing.settle_run(db_session, settings, session_id=session_id, run_id=run.id)
    assert charged == 6  # 2 + 4

    # 同一条 run 再结算：水位里已经记过，差为 0
    assert await billing.settle_run(db_session, settings, session_id=session_id, run_id=run.id) == 0

    rows = list(
        await db_session.scalars(
            select(CreditLedger).where(CreditLedger.run_id == run.id, CreditLedger.reason == CHAT)
        )
    )
    assert len(rows) == 1
    assert rows[0].delta == -6
    assert rows[0].usage["total_tokens"] == 1_500_000
    user = await db_session.get(User, TEST_USER_ID)
    assert user is not None and user.credits_balance == 94


async def test_settle_run_disabled_does_nothing(db_session: AsyncSession) -> None:
    await _user(db_session)
    session_id = await make_session(db_session)
    run = await _make_run(db_session, session_id, TokenUsage(input_tokens=1_000_000))

    assert (
        await billing.settle_run(
            db_session, _settings(billing_enabled=False), session_id=session_id, run_id=run.id
        )
        == 0
    )
    user = await db_session.get(User, TEST_USER_ID)
    assert user is not None and user.credits_balance == 100


async def test_settle_run_falls_back_to_default_rate(db_session: AsyncSession) -> None:
    await _user(db_session)
    session_id = await make_session(db_session)
    run = await _make_run(db_session, session_id, TokenUsage(output_tokens=1_000_000))
    # 模型没单独配单价 → 走全局默认（输出 8 分 / 1M）
    settings = _settings(credit_default_output_per_1m=8.0)

    assert await billing.settle_run(db_session, settings, session_id=session_id, run_id=run.id) == 8


# --------------------------------------------------------------------- 拦截


async def test_require_credits_blocks_empty_balance(db_session: AsyncSession) -> None:
    user = await ensure_test_user(db_session)
    user.credits_balance = 0
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await billing.require_credits(db_session, _settings(), user.id)
    assert exc_info.value.status_code == 402

    # 充了就放行；计费关闭时余额为零也放行
    user.credits_balance = 10
    await db_session.commit()
    await billing.require_credits(db_session, _settings(), user.id)
    await billing.require_credits(db_session, _settings(billing_enabled=False), user.id)


# --------------------------------------------------------------------- 图片 / 人工调整


async def test_charge_images(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    model = ImageModel(name=f"img-{uuid4().hex[:8]}", provider="openai", model_name="img-test")
    db_session.add(model)
    await db_session.commit()
    settings = _settings(credit_default_per_image=20.0)
    run_id = uuid4()

    charged = await billing.charge_images(
        db_session, settings, user_id=user.id, model=model, count=2, run_id=run_id
    )
    assert charged == 40
    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None and refreshed.credits_balance == 60

    totals = await billing.run_charge_totals(db_session, run_id)
    assert totals.credits == 40
    assert totals.images == 2

    # 开关关掉就一分不扣
    assert (
        await billing.charge_images(
            db_session, _settings(billing_enabled=False), user_id=user.id, model=model, count=2
        )
        == 0
    )


async def test_charge_images_can_overdraw(db_session: AsyncSession) -> None:
    """余额 100、出图 200：照实扣成 -100，台账也是完整金额。"""
    user = await _user(db_session)
    model = ImageModel(
        name=f"img-overdraw-{uuid4().hex[:8]}", provider="openai", model_name="img-test"
    )
    db_session.add(model)
    await db_session.commit()

    charged = await billing.charge_images(
        db_session,
        _settings(credit_default_per_image=200.0),
        user_id=user.id,
        model=model,
        count=1,
        run_id=uuid4(),
    )

    assert charged == 200
    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None and refreshed.credits_balance == -100
    entry = (
        await db_session.scalars(select(CreditLedger).where(CreditLedger.user_id == user.id))
    ).one()
    assert entry.delta == -200
    assert entry.balance_after == -100


async def test_adjust_allows_negative_balance(db_session: AsyncSession) -> None:
    user = await _user(db_session)

    await billing.adjust(db_session, user_id=user.id, delta=50, note="内测奖励")
    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None and refreshed.credits_balance == 150

    # 一次扣 500：余额变成 -350，下次充值抵扣
    await billing.adjust(db_session, user_id=user.id, delta=-500)
    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None and refreshed.credits_balance == -350


async def test_adjust_records_the_full_delta(db_session: AsyncSession) -> None:
    """余额 100 扣 500：流水记满 -500，余额同步到 -400。"""
    user = await _user(db_session)

    applied = await billing.adjust(db_session, user_id=user.id, delta=-500)

    assert applied == -500
    entry = (
        await db_session.scalars(select(CreditLedger).where(CreditLedger.user_id == user.id))
    ).one()
    assert entry.delta == -500
    assert entry.balance_after == -400


async def test_adjust_unknown_user_raises(db_session: AsyncSession) -> None:
    """查不到用户要当场报错：静默返回 0 会让管理员点了没反应。"""
    with pytest.raises(NotFoundError):
        await billing.adjust(db_session, user_id=uuid4(), delta=10)


# ------------------------------------------------------------------ 用量守卫


def _guard_for(
    session_factory: Any,
    settings: Settings,
    session_id: Any,
    run: SessionRun,
    owner_id: Any,
) -> Any:
    return credit_guard.make_usage_guard(
        session_factory,
        settings,
        session_id=session_id,
        run_id=run.id,
        owner_id=owner_id,
    )


async def _priced_run(db_session: AsyncSession) -> tuple[Any, SessionRun]:
    """一条欠 6 分文本用量的 run：1M 输入 × 2 + 0.5M 输出 × 8。"""
    session_id = await make_session(db_session)
    model = _model(db_session, credit_input_per_1m=2.0, credit_output_per_1m=8.0)
    db_session.add(model)
    await db_session.commit()
    run = await _make_run(
        db_session,
        session_id,
        TokenUsage(input_tokens=1_000_000, output_tokens=500_000),
        model_id=model.id,
    )
    return session_id, run


async def test_usage_guard_settles_without_cutting_off(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    user = await _user(db_session)  # 余额 100
    session_id, run = await _priced_run(db_session)
    guard = _guard_for(db_session_factory, _settings(), session_id, run, user.id)

    await guard(TokenUsage())

    # 守卫另开一条连接写库，测试会话里那个 User 还是扣费前的快照
    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.credits_balance == 94


async def test_usage_guard_raises_when_balance_hits_zero(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    """余额被本轮用光：守卫只抛出停止信号，条目和事件由 AgentTurn 那一侧产出。"""
    user = await _user(db_session)
    user.credits_balance = 6
    await db_session.commit()
    session_id, run = await _priced_run(db_session)
    guard = _guard_for(db_session_factory, _settings(), session_id, run, user.id)

    with pytest.raises(CreditsExhausted):
        await guard(TokenUsage())

    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.credits_balance == 0


async def test_usage_guard_disabled_touches_nothing(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    user = await _user(db_session)
    session_id, run = await _priced_run(db_session)
    settings = _settings(billing_enabled=False)
    guard = _guard_for(db_session_factory, settings, session_id, run, user.id)

    await guard(TokenUsage())

    refreshed = await db_session.get(User, TEST_USER_ID)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.credits_balance == 100


async def test_store_swallows_observer_faults_but_not_the_stop_signal(
    db_session: AsyncSession,
) -> None:
    """分界在 SessionStore：计费查库炸了不打断对话，但「本轮该停」必须放行。"""
    session_id = await make_session(db_session)

    async def broken_observer(_: TokenUsage) -> None:
        raise RuntimeError("db down")

    faulted = SessionStore(db_session, session_id, on_usage=broken_observer)
    await faulted.append_items([], usage=TokenUsage(input_tokens=10))

    async def stopping_observer(_: TokenUsage) -> None:
        raise CreditsExhausted("out of credits")

    stopping = SessionStore(db_session, session_id, on_usage=stopping_observer)
    with pytest.raises(CreditsExhausted):
        await stopping.append_items([], usage=TokenUsage(input_tokens=10))
