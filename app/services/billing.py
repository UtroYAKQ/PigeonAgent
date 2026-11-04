"""积分计费：换算与记账的唯一出口。

接入点只有两处，其余模块（agent / store / 事件流 / 前端）不认识积分：

- 文本：run 收尾时 `settle_run`，按 `session_run.usage` 结算一次；
- 图片：出图工具成功返回后 `charge_images`，按张数结算。

文本不能在每个 usage 事件上扣：一 run 会触发十几次 flush，还要处理
压缩、resume、重跑。所以结算放在收尾，用「本 run 已结算过的用量水位」
做差 —— 重复调用时差为 0，天然幂等。水位就存在该 run 的 chat 流水里。

单价粒度是"每 100 万 token 多少积分"，与各家官方报价口径一致。缓存
token（cache_read / cache_write）暂不计入：口径可解释优先，要打折时在
price_tokens 里加一项即可。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, NotFoundError
from app.domain.run_items import TokenUsage
from app.models.credit_ledger import ADJUST, CHAT, IMAGE, CreditLedger
from app.models.image_model import ImageModel
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.models.user import User

logger = logging.getLogger(__name__)

PER_MILLION = 1_000_000
MODEL_KIND_LLM = "llm"
MODEL_KIND_IMAGE = "image"


class InsufficientCreditsError(AppError):
    status_code = 402


@dataclass(frozen=True, slots=True)
class TokenRate:
    """每 100 万 token 的积分单价。"""

    input_per_1m: float
    output_per_1m: float
    # 缓存命中价；留空按输入价，保持旧行为
    cache_read_per_1m: float | None = None


def token_rate(model: LlmModel | None, settings: Settings) -> TokenRate:
    """模型没单独配就回落到全局默认。"""
    return TokenRate(
        input_per_1m=_first(
            model.credit_input_per_1m if model else None, settings.credit_default_input_per_1m
        ),
        output_per_1m=_first(
            model.credit_output_per_1m if model else None, settings.credit_default_output_per_1m
        ),
        cache_read_per_1m=model.credit_cache_read_per_1m if model else None,
    )


def image_rate(model: ImageModel | None, settings: Settings) -> float:
    return _first(model.credit_per_image if model else None, settings.credit_default_per_image)


def _first(*candidates: float | None) -> float:
    for value in candidates:
        if value is not None:
            return float(value)
    return 0.0


def price_tokens(usage: TokenUsage, rate: TokenRate) -> float:
    """纯函数：严格线性折算，保留 6 位小数。

    不做"不足 1 分也扣 1 分"：那会把一次小调用放大几百倍（1.9K token
    折算 0.0017 分，取整后变 1 分）。小数积分下水位差机制天然累积，
    多少用量就扣多少钱。

    缓存命中 token 已经包含在 input_tokens 里（OpenAI 兼容口径），计费时
    从输入里扣出来按缓存价算；缓存写入没有独立单价，仍按输入价计入。
    """
    cached = min(max(usage.cache_read_tokens, 0), max(usage.input_tokens, 0))
    billable_input = max(usage.input_tokens - cached, 0)
    cache_rate = rate.cache_read_per_1m if rate.cache_read_per_1m is not None else rate.input_per_1m
    raw = (
        billable_input / PER_MILLION * rate.input_per_1m
        + cached / PER_MILLION * cache_rate
        + usage.output_tokens / PER_MILLION * rate.output_per_1m
    )
    return round(raw, 6) if raw > 0 else 0.0


def price_images(count: int, per_image: float) -> float:
    if count <= 0 or per_image <= 0:
        return 0.0
    return round(count * per_image, 6)


# --------------------------------------------------------------------- 记账


async def balance_of(db: AsyncSession, user_id: UUID) -> float:
    user = await db.get(User, user_id)
    return user.credits_balance if user is not None else 0.0


async def require_credits(db: AsyncSession, settings: Settings, user_id: UUID) -> None:
    """发起对话前拦截：余额见底就直接拒绝，不让他们跑完才发现欠账。"""
    if not settings.billing_enabled:
        return
    if await balance_of(db, user_id) <= 0:
        raise InsufficientCreditsError("积分不足，请联系管理员充值")


async def settle_run(
    db: AsyncSession, settings: Settings, *, session_id: UUID, run_id: UUID
) -> float:
    """结算一条 run 的文本用量；返回实际扣掉的积分（幂等：重复调用返回 0）。"""
    if not settings.billing_enabled:
        return 0
    run = await db.get(SessionRun, run_id)
    if run is None or run.session_id != session_id:
        return 0
    owner_id = await db.scalar(select(ChatSession.owner_id).where(ChatSession.id == session_id))
    if owner_id is None:
        return 0

    delta = run.usage.subtract(await _billed_usage(db, run_id))
    if not delta.has_values():
        return 0
    model = await db.get(LlmModel, run.model_id) if run.model_id is not None else None
    amount = price_tokens(delta, token_rate(model, settings))
    if amount <= 0:
        return 0
    return await _charge(
        db,
        user_id=owner_id,
        amount=amount,
        reason=CHAT,
        run_id=run_id,
        model_kind=MODEL_KIND_LLM,
        model_id=run.model_id,
        usage=delta.model_dump(),
    )


async def charge_images(
    db: AsyncSession,
    settings: Settings,
    *,
    user_id: UUID,
    model: ImageModel | None,
    count: int,
    run_id: UUID | None = None,
) -> float:
    """一次成功出图记一笔；重跑会真的重新出图，所以不需要做差。"""
    if not settings.billing_enabled:
        return 0
    amount = price_images(count, image_rate(model, settings))
    if amount <= 0:
        return 0
    return await _charge(
        db,
        user_id=user_id,
        amount=amount,
        reason=IMAGE,
        run_id=run_id,
        model_kind=MODEL_KIND_IMAGE,
        model_id=model.id if model is not None else None,
        usage={"images": count},
    )


async def adjust(
    db: AsyncSession, *, user_id: UUID, delta: float, note: str | None = None
) -> float:
    """管理员手工充值/扣减；正数充、负数扣，返回实际生效的差额。"""
    if delta == 0:
        return 0
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    # 扣减允许把余额压到负数；欠账由下一次充值抵扣，台账才反映真实用量
    user.credits_balance += delta
    db.add(
        CreditLedger(
            user_id=user.id,
            delta=delta,
            balance_after=user.credits_balance,
            reason=ADJUST,
            note=note,
            usage={},
        )
    )
    await db.commit()
    return delta


async def _billed_usage(db: AsyncSession, run_id: UUID) -> TokenUsage:
    """该 run 已结算过的用量水位 = 所有 chat 流水的 usage 之和。"""
    rows = await db.scalars(
        select(CreditLedger.usage).where(CreditLedger.run_id == run_id, CreditLedger.reason == CHAT)
    )
    total = TokenUsage()
    for raw in rows:
        if isinstance(raw, dict) and raw:
            total = total.merged(TokenUsage.model_validate(raw))
    return total


async def _charge(
    db: AsyncSession,
    *,
    user_id: UUID,
    amount: float,
    reason: str,
    run_id: UUID | None,
    model_kind: str | None,
    model_id: int | None,
    usage: dict[str, Any],
) -> float:
    """扣余额并写流水；余额不够就如实扣成负数，等下次充值抵扣。"""
    user = await db.get(User, user_id)
    if user is None:
        return 0
    user.credits_balance -= amount
    db.add(
        CreditLedger(
            user_id=user.id,
            delta=-amount,
            balance_after=user.credits_balance,
            reason=reason,
            run_id=run_id,
            model_kind=model_kind,
            model_id=model_id,
            usage=usage,
        )
    )
    await db.commit()
    if user.credits_balance < 0:
        logger.warning(
            "User %s balance went negative (%s) after charging %s (%s)",
            user_id,
            user.credits_balance,
            amount,
            reason,
        )
    return amount
