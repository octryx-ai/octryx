"""Quota usage forecasts per budget policy and period."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetPolicy, QuotaUsageForecast
from .accounting import _ZERO
from .policy_scope import _load_usage_snapshot, _period_key


async def record_forecast(
    db: AsyncSession,
    *,
    policy: BudgetPolicy,
    forecasted_tokens: int,
    forecasted_cost: Decimal,
) -> QuotaUsageForecast:
    """Upsert forecasted usage for the policy's current period."""
    period = _period_key(policy)
    existing = (
        await db.execute(
            select(QuotaUsageForecast).where(
                QuotaUsageForecast.policy_id == policy.id,
                QuotaUsageForecast.period_key == period,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.forecasted_tokens = forecasted_tokens
        existing.forecasted_cost = forecasted_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        await db.commit()
        await db.refresh(existing)
        return existing
    forecast = QuotaUsageForecast(
        id=str(uuid.uuid4()),
        policy_id=policy.id,
        period_key=period,
        forecasted_tokens=forecasted_tokens,
        actual_tokens=0,
        forecasted_cost=forecasted_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        actual_cost=_ZERO,
    )
    db.add(forecast)
    await db.commit()
    await db.refresh(forecast)
    return forecast


async def update_forecast_actuals(
    db: AsyncSession,
    *,
    policy: BudgetPolicy,
) -> QuotaUsageForecast | None:
    """Sync actual usage into the forecast row for the current period."""
    period = _period_key(policy)
    snapshot = await _load_usage_snapshot(db, policy=policy)
    existing = (
        await db.execute(
            select(QuotaUsageForecast).where(
                QuotaUsageForecast.policy_id == policy.id,
                QuotaUsageForecast.period_key == period,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        return None
    existing.actual_tokens = snapshot.tokens
    existing.actual_cost = snapshot.cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    await db.commit()
    await db.refresh(existing)
    return existing


async def list_quota_forecasts(
    db: AsyncSession,
    *,
    policy_id: str,
) -> list[QuotaUsageForecast]:
    rows = (
        await db.execute(
            select(QuotaUsageForecast)
            .where(QuotaUsageForecast.policy_id == policy_id)
            .order_by(QuotaUsageForecast.period_key.desc())
        )
    ).scalars().all()
    return list(rows)
