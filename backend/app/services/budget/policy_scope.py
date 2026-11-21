"""Which budget policies apply to a call, their reset window and limits, and the usage inside that window."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetPolicy, LLMProvider, Session, UsageEvent
from ...models.runtime.budget import (
    RESET_PERIOD_DAILY,
    RESET_PERIOD_MONTHLY,
    RESET_PERIOD_WEEKLY,
)
from ...time_utils import utc_now
from .accounting import BudgetUsageSnapshot, _to_decimal


async def _list_applicable_policies(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None,
    agent_chain_id: str | None = None,
    flow_definition_id: str | None = None,
    provider_id: str | None = None,
) -> list[BudgetPolicy]:
    """Return active policies that apply to the given scope dimensions.

    A policy matches when every non-null scope dimension on the policy matches
    the corresponding call argument.  Global policies (all dimensions null) are
    excluded — every policy must be scoped to at least one dimension.
    """
    stmt = select(BudgetPolicy).where(BudgetPolicy.is_active)
    rows = (await db.execute(stmt)).scalars().all()
    applicable: list[BudgetPolicy] = []
    for row in rows:
        # Skip policies whose scope doesn't match
        if row.user_id and row.user_id != user_id:
            continue
        if row.project_id and row.project_id != project_id:
            continue
        if row.agent_chain_id and row.agent_chain_id != agent_chain_id:
            continue
        if row.flow_definition_id and row.flow_definition_id != flow_definition_id:
            continue
        if row.provider_id:
            # provider_id on policy is an FK to llm_providers; compare by id
            if row.provider_id != provider_id:
                continue
        # Policy must have at least one binding dimension
        has_scope = any([
            row.user_id,
            row.project_id,
            row.team_id,
            row.agent_chain_id,
            row.flow_definition_id,
            row.provider_id,
            row.domain_pack_id,
        ])
        if not has_scope:
            continue
        applicable.append(row)
    return applicable


def _policy_window(policy: BudgetPolicy, now: Any = None) -> tuple[Any, Any]:
    """Return (start, end) UTC datetimes for the policy's reset window at ``now`` (default: the current time)."""
    now = now or utc_now()
    period = (policy.reset_period or RESET_PERIOD_DAILY).lower()
    if period == RESET_PERIOD_DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == RESET_PERIOD_WEEKLY:
        # Monday-based ISO week
        today = now.date()
        monday = today - timedelta(days=today.weekday())
        start = now.replace(year=monday.year, month=monday.month, day=monday.day,
                            hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(weeks=1)
    elif period == RESET_PERIOD_MONTHLY:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # First day of next month
        if now.month == 12:
            end = start.replace(year=now.year + 1, month=1)
        else:
            end = start.replace(month=now.month + 1)
    else:
        # never / unknown — use a very wide window (all time)
        import datetime
        start = datetime.datetime(2000, 1, 1)
        end = datetime.datetime(2099, 12, 31)
    return start, end


def _period_key(policy: BudgetPolicy) -> str:
    """Return a string key for the current period (for QuotaUsageForecast)."""
    now = utc_now()
    period = (policy.reset_period or RESET_PERIOD_DAILY).lower()
    if period == RESET_PERIOD_DAILY:
        return now.strftime("%Y-%m-%d")
    elif period == RESET_PERIOD_WEEKLY:
        return now.strftime("%Y-W%W")
    elif period == RESET_PERIOD_MONTHLY:
        return now.strftime("%Y-%m")
    else:
        return "all"


def _get_limits_for_period(policy: BudgetPolicy) -> tuple[Any, Any, Any]:
    """Return (request_limit, token_limit, cost_limit) for the policy's reset period."""
    period = (policy.reset_period or RESET_PERIOD_DAILY).lower()
    if period == RESET_PERIOD_WEEKLY:
        return policy.weekly_request_limit, policy.weekly_token_limit, policy.weekly_cost_limit
    if period == RESET_PERIOD_MONTHLY:
        return policy.monthly_request_limit, policy.monthly_token_limit, policy.monthly_cost_limit
    return policy.daily_request_limit, policy.daily_token_limit, policy.daily_cost_limit  # daily or never


async def _load_usage_snapshot(
    db: AsyncSession,
    *,
    policy: BudgetPolicy,
) -> BudgetUsageSnapshot:
    start, end = _policy_window(policy)
    stmt = (
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.tokens_in), 0),
            func.coalesce(func.sum(UsageEvent.tokens_out), 0),
            func.coalesce(func.sum(UsageEvent.cost), 0),
        )
        .select_from(UsageEvent)
        .join(Session, Session.id == UsageEvent.session_id)
        .where(
            UsageEvent.created_at >= start,
            UsageEvent.created_at < end,
        )
    )
    if policy.user_id:
        stmt = stmt.where(UsageEvent.user_id == policy.user_id)
    if policy.project_id:
        stmt = stmt.where(Session.project_id == policy.project_id)
    if policy.agent_chain_id:
        stmt = stmt.where(UsageEvent.agent_chain_id == policy.agent_chain_id)
    if policy.flow_definition_id:
        stmt = stmt.where(UsageEvent.flow_definition_id == policy.flow_definition_id)
    if policy.provider_id:
        # Match by provider name via join to llm_providers
        stmt = (
            stmt.join(LLMProvider, LLMProvider.name == UsageEvent.provider)
            .where(LLMProvider.id == policy.provider_id)
        )
    row = (await db.execute(stmt)).one()
    return BudgetUsageSnapshot(
        requests=int(row[0] or 0),
        tokens=int((row[1] or 0) + (row[2] or 0)),
        cost=_to_decimal(row[3]).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
    )


async def _load_session_usage_cost(db: AsyncSession, *, session_id: str) -> Decimal:
    row = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0)).where(UsageEvent.session_id == session_id)
        )
    ).scalar_one()
    return _to_decimal(row).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
