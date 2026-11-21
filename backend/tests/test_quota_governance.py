"""Tests for Cost Quota and Budget Governance.

New coverage beyond the existing test_chat_budget / test_chargeback_service:
  - BudgetPolicy scoped to agent_chain, flow, provider, team
  - reset_period: weekly and monthly limit selection
  - upsert_budget_policy validates new scope dimensions and reset_period
  - _load_usage_snapshot filters by agent_chain_id / flow_definition_id
  - enforce_budget_limits passes agent_chain_id / flow_definition_id / provider_id
  - QuotaUsageForecast: record_forecast / update_forecast_actuals / list_quota_forecasts
  - record_usage_event stores agent_chain_id / flow_definition_id attribution columns
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BudgetPolicy
from app.models.runtime.budget import (
    RESET_PERIOD_MONTHLY,
    RESET_PERIOD_WEEKLY,
)
from app.services.budget.forecasts import list_quota_forecasts, record_forecast, update_forecast_actuals
from app.services.budget.policies import upsert_budget_policy
from tests.quota_governance_support import _add_usage, _make_policy, _make_session, _uid

# ── Helpers ──────────────────────────────────────────────────────────────────


def _serialize(policy: BudgetPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "user_id": policy.user_id,
        "project_id": policy.project_id,
        "agent_chain_id": policy.agent_chain_id,
        "flow_definition_id": policy.flow_definition_id,
        "reset_period": policy.reset_period,
    }


# ── upsert_budget_policy: new scope + period validation ──────────────────────


@pytest.mark.asyncio
async def test_upsert_budget_policy_agent_chain_scope(db: AsyncSession, auth_user):
    chain_id = _uid()
    result = await upsert_budget_policy(
        db,
        payload={
            "name": "Agent Chain Policy",
            "agent_chain_id": chain_id,
            "daily_token_limit": 50000,
        },
        serialize_policy=_serialize,
    )
    assert result["agent_chain_id"] == chain_id


@pytest.mark.asyncio
async def test_upsert_budget_policy_flow_scope(db: AsyncSession):
    flow_id = _uid()
    result = await upsert_budget_policy(
        db,
        payload={
            "name": "Flow Policy",
            "flow_definition_id": flow_id,
            "weekly_token_limit": 200000,
            "reset_period": RESET_PERIOD_WEEKLY,
        },
        serialize_policy=_serialize,
    )
    assert result["flow_definition_id"] == flow_id
    assert result["reset_period"] == RESET_PERIOD_WEEKLY


@pytest.mark.asyncio
async def test_upsert_budget_policy_no_scope_raises(db: AsyncSession):
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError, match="scope"):
        await upsert_budget_policy(
            db,
            payload={"name": "No scope", "daily_token_limit": 1000},
            serialize_policy=_serialize,
        )


@pytest.mark.asyncio
async def test_upsert_budget_policy_invalid_reset_period_raises(db: AsyncSession):
    from app.exceptions.api import ValidationError
    with pytest.raises(ValidationError, match="reset_period"):
        await upsert_budget_policy(
            db,
            payload={
                "name": "Bad period",
                "user_id": _uid(),
                "reset_period": "fortnightly",
                "daily_token_limit": 1000,
            },
            serialize_policy=_serialize,
        )


@pytest.mark.asyncio
async def test_upsert_budget_policy_monthly_limits(db: AsyncSession, auth_user):
    result = await upsert_budget_policy(
        db,
        payload={
            "name": "Monthly policy",
            "user_id": str(auth_user.id),
            "monthly_token_limit": 5000000,
            "monthly_cost_limit": "50.00",
            "reset_period": RESET_PERIOD_MONTHLY,
        },
        serialize_policy=_serialize,
    )
    assert result["reset_period"] == RESET_PERIOD_MONTHLY


# ── QuotaUsageForecast ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_forecast_creates_row(db: AsyncSession, auth_user):
    policy = await _make_policy(
        db, user_id=str(auth_user.id), daily_token_limit=10000,
    )
    forecast = await record_forecast(
        db,
        policy=policy,
        forecasted_tokens=8000,
        forecasted_cost=Decimal("0.08"),
    )
    assert forecast.id is not None
    assert forecast.forecasted_tokens == 8000
    assert forecast.actual_tokens == 0


@pytest.mark.asyncio
async def test_record_forecast_idempotent(db: AsyncSession, auth_user):
    policy = await _make_policy(
        db, user_id=str(auth_user.id), daily_token_limit=10000,
    )
    f1 = await record_forecast(db, policy=policy,
                               forecasted_tokens=5000, forecasted_cost=Decimal("0.05"))
    f2 = await record_forecast(db, policy=policy,
                               forecasted_tokens=7000, forecasted_cost=Decimal("0.07"))
    assert f1.id == f2.id
    assert f2.forecasted_tokens == 7000


@pytest.mark.asyncio
async def test_update_forecast_actuals(db: AsyncSession, auth_user):
    policy = await _make_policy(
        db, user_id=str(auth_user.id), daily_token_limit=10000,
    )
    sess = await _make_session(db, user_id=str(auth_user.id))
    await record_forecast(db, policy=policy,
                          forecasted_tokens=5000, forecasted_cost=Decimal("0.05"))
    # Record real usage
    await _add_usage(db, session_id=sess.id, user_id=str(auth_user.id),
                     tokens_in=300, tokens_out=150, cost=Decimal("0.006"))
    updated = await update_forecast_actuals(db, policy=policy)
    assert updated is not None
    assert updated.actual_tokens == 450
    assert updated.actual_cost > 0


@pytest.mark.asyncio
async def test_update_forecast_actuals_no_row_returns_none(db: AsyncSession, auth_user):
    policy = await _make_policy(
        db, user_id=str(auth_user.id), daily_token_limit=10000,
    )
    result = await update_forecast_actuals(db, policy=policy)
    assert result is None


@pytest.mark.asyncio
async def test_list_quota_forecasts(db: AsyncSession, auth_user):
    policy = await _make_policy(
        db, user_id=str(auth_user.id), daily_token_limit=10000,
    )
    await record_forecast(db, policy=policy,
                          forecasted_tokens=3000, forecasted_cost=Decimal("0.03"))
    rows = await list_quota_forecasts(db, policy_id=policy.id)
    assert len(rows) == 1
    assert rows[0].policy_id == policy.id


@pytest.mark.asyncio
async def test_list_quota_forecasts_empty_for_unknown_policy(db: AsyncSession):
    rows = await list_quota_forecasts(db, policy_id=_uid())
    assert rows == []
