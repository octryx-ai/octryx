"""Cost quota and budget governance: scoped budget policies, weekly and monthly reset periods, usage
filtering and the attribution columns."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BudgetPolicy
from app.models.runtime.budget import (
    RESET_PERIOD_MONTHLY,
    RESET_PERIOD_WEEKLY,
)
from app.services.budget.policies import upsert_budget_policy
from tests.quota_governance_support import _uid

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
