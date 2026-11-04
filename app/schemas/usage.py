"""个人用量视图的响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UsageTotals(BaseModel):
    today_tokens: int = 0
    today_credits: float = 0.0
    today_cache_read_tokens: int = 0
    month_tokens: int = 0
    month_credits: float = 0.0
    month_cache_read_tokens: int = 0
    month_runs: int = 0
    runs_total: int = 0
    range_input_tokens: int = 0
    range_output_tokens: int = 0
    range_cache_read_tokens: int = 0
    range_credits: float = 0.0


class UsageDaily(BaseModel):
    date: str  # YYYY-MM-DD（UTC）
    tokens: int = 0
    credits: float = 0.0
    runs: int = 0
    cache_read_tokens: int = 0


class UsageModelStat(BaseModel):
    model_name: str | None = None
    runs: int = 0
    tokens: int = 0
    credits: float = 0.0
    cache_read_tokens: int = 0


class UsageRecent(BaseModel):
    created_at: datetime
    model_name: str | None = None
    status: str
    total_tokens: int = 0
    cache_read_tokens: int = 0
    credits_charged: float = 0.0
    images_generated: int = 0


class UsageOverview(BaseModel):
    balance: float = 0.0
    billing_enabled: bool = False
    totals: UsageTotals = UsageTotals()
    daily: list[UsageDaily] = []
    by_model: list[UsageModelStat] = []
    recent: list[UsageRecent] = []
