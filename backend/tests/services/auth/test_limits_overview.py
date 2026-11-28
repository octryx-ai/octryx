"""Limits & budgets overview: Workspace overrides, environment limits, budget periods."""

from __future__ import annotations

import uuid

import pytest

from app.models import BudgetPolicy, Project
from app.services.auth import create_access_token

ROUTE = "/api/v1/admin/limits/overview"


@pytest.mark.asyncio
async def test_the_overview_lists_overrides_environment_limits_and_budget_periods(client, db, auth_user):
    capped = Project(id=str(uuid.uuid4()), name="Capped Desk", is_active=True,
                     config={"runtime_cost_limits": {"agent_request_cost_limit_usd": "5"},
                             "agent_gateway_policy": {"session_budget": {"per_user_daily_usd": 20}}})
    plain = Project(id=str(uuid.uuid4()), name="Plain Desk", is_active=True, config={})
    db.add_all([capped, plain])
    await db.flush()
    db.add(BudgetPolicy(name="Capped monthly", project_id=capped.id, reset_period="monthly",
                        monthly_cost_limit=800, warn_at_percent=80, block_at_percent=100))
    await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(auth_user.id)}"}

    body = (await client.get(ROUTE, headers=headers)).json()

    request_caps = body["workspace_overrides"]["agent_request_cost_limit_usd"]
    assert [item["name"] for item in request_caps if item["name"] in {"Capped Desk", "Plain Desk"}] == ["Capped Desk"]
    assert any(item["value"] == "20" for item in body["workspace_overrides"]["gateway_daily_usd_per_person"])
    assert {item["key"] for item in body["environment_limits"]} >= {"rate_limit_user_read_per_min"}
    budget = next(item for item in body["budgets"] if item["name"] == "Capped monthly")
    assert (budget["scope"], budget["scope_label"], budget["period"]) == ("workspace", "Capped Desk", "monthly")
    assert float(budget["amount_usd"]) == 800 and float(budget["used_usd"]) == 0
    assert (await client.get(ROUTE)).status_code == 401
