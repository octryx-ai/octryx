"""Usage & costs from usage_events, priced coverage, unpriced models under a cost cap."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import LLMModel, LLMProvider, UsageEvent
from app.services.budget import enforce_budget_limits
from app.services.budget.unpriced_guard import (
    UnpricedModelUnderCostCapError,
    set_unpriced_model_policy,
)
from app.services.observability.usage_read_model import usage_overview, window_bounds
from tests.observability_support import admin_user, call_as, session_for, user_with_role, workspace

MODEL = "anthropic.example-unpriced-v1:0"


def _event(session, user, *, model, status, cost, tokens=1000, provider="bedrock", cache=0):
    return UsageEvent(session_id=session.id, user_id=user.id, provider=provider, model=model, tokens_in=tokens,
                      tokens_out=100, cache_read_tokens=cache, cost=Decimal(str(cost)), cost_status=status)


async def _bedrock_model(db, *, priced: bool) -> LLMModel:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.name == "bedrock"))).scalars().first()
    if provider is None:
        provider = LLMProvider(id=str(uuid.uuid4()), name="bedrock", driver="bedrock_api", display_name="Bedrock", is_active=True,
                               is_global=True, auth_mode="aws_credentials", aws_region="eu-central-1")
        db.add(provider)
        await db.flush()
    model = LLMModel(provider_id=provider.id, model_id=MODEL, display_name="Example",
                     pricing_input=3.0 if priced else None, pricing_output=15.0 if priced else None)
    db.add(model)
    await db.flush()
    return model


@pytest.mark.asyncio
async def test_usage_counts_priced_spend_coverage_cache_and_breakdowns(db):
    admin = await admin_user(db)
    project = await workspace(db)
    session = await session_for(db, admin, project=project)
    db.add_all([
        _event(session, admin, model="priced-model", status="catalog_pricing", cost=2.5, cache=500),
        _event(session, admin, model=MODEL, status="missing_pricing", cost=0, tokens=3000),
        _event(session, admin, model="seat-model", status="not_billed_to_platform", cost=0, provider="anthropic_seat"),
    ])
    await db.commit()
    start, end = window_bounds("month")

    usage = await usage_overview(db, window="month")

    total = (await db.execute(select(func.coalesce(func.sum(UsageEvent.cost), 0)).where(
        UsageEvent.created_at >= start, UsageEvent.created_at < end))).scalar()
    tiles = usage["tiles"]
    assert tiles["spend"] == pytest.approx(float(total))
    priced_tokens, unpriced_tokens = 1000 + 100 + 500, 3000 + 100
    assert tiles["unpriced_tokens"] >= unpriced_tokens
    assert 0 < tiles["priced_coverage"] < 1
    assert tiles["cache_tokens"] >= 500
    models = {item["model"]: item for item in usage["by_model"]}
    assert models[MODEL]["pricing"] == "unpriced"
    assert models["priced-model"]["pricing"] == "priced" and models["priced-model"]["tokens"] == priced_tokens
    assert models["seat-model"]["pricing"] == "not_billed"
    assert any(row["workspace_id"] == project.id and row["cost"] == 2.5 for row in usage["by_workspace"])
    assert usage["daily"] and usage["daily"][-1]["spend"] >= 2.5
    assert [row["limit"] for row in usage["budgets"]][:2] == ["Per request", "Per session"]


@pytest.mark.asyncio
async def test_an_unpriced_platform_billed_model_under_a_cap_needs_configuration(db):
    admin = await admin_user(db)
    session = await session_for(db, admin)
    await _bedrock_model(db, priced=False)
    await set_unpriced_model_policy(db, "block")
    await db.commit()
    call = {"session_id": session.id, "user_id": admin.id, "project_id": None,
            "messages": [{"role": "user", "content": "hello"}], "max_completion_tokens": 100,
            "approx_chars_per_token": 4}

    with pytest.raises(UnpricedModelUnderCostCapError) as refused:
        await enforce_budget_limits(db, runtimes=[{"provider_name": "bedrock", "model": MODEL}], **call)
    assert refused.value.state == "needs_configuration"
    assert "Runtime → Model catalog" in str(refused.value) and MODEL in str(refused.value)

    await enforce_budget_limits(db, runtimes=[{"provider_name": "litellm_gateway", "driver": "litellm_gateway", "model": "alias"}], **call)
    await set_unpriced_model_policy(db, "warn")
    await enforce_budget_limits(db, runtimes=[{"provider_name": "bedrock", "model": MODEL}], **call)


@pytest.mark.asyncio
async def test_platform_billing_is_decided_by_the_driver_not_the_provider_name(db):
    admin = await admin_user(db)
    session = await session_for(db, admin)
    suffix = uuid.uuid4().hex[:6]
    db.add_all([
        LLMProvider(id=str(uuid.uuid4()), name=f"company-models-{suffix}", driver="litellm_gateway",
                    display_name="Company models", is_active=True, is_global=True),
        LLMProvider(id=str(uuid.uuid4()), name=f"litellm-eu-{suffix}", driver="bedrock_api",
                    display_name="Bedrock EU", is_active=True, is_global=True),
    ])
    await set_unpriced_model_policy(db, "block")
    await db.commit()
    call = {"session_id": session.id, "user_id": admin.id, "project_id": None,
            "messages": [{"role": "user", "content": "hello"}], "max_completion_tokens": 100,
            "approx_chars_per_token": 4}

    await enforce_budget_limits(db, runtimes=[{"provider_name": f"company-models-{suffix}", "model": "team-alias"}],
                                **call)
    with pytest.raises(UnpricedModelUnderCostCapError):
        await enforce_budget_limits(db, runtimes=[{"provider_name": f"litellm-eu-{suffix}", "model": MODEL}], **call)


@pytest.mark.asyncio
async def test_the_gateway_answers_an_unpriced_model_with_needs_configuration(monkeypatch):
    from types import SimpleNamespace

    from app.services.model_gateway.inbound import governed_dispatch as inbound

    async def daily_ok(*_args, **_kwargs):
        return SimpleNamespace(allowed=True)

    async def unpriced(*_args, **_kwargs):
        raise UnpricedModelUnderCostCapError(provider_name="bedrock", model_id=MODEL)

    monkeypatch.setattr(inbound, "check_daily_budget", daily_ok)
    monkeypatch.setattr(inbound, "enforce_budget_limits", unpriced)
    admitted = SimpleNamespace(provider_name="bedrock", entry=SimpleNamespace(alias="team-alias"))
    identity = SimpleNamespace(user=SimpleNamespace(id="u1"), workspace_id=None)

    response = await inbound.dispatch_governed(
        None, headers={}, identity=identity, session_id="s1",
        body={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}, payload=b"{}", admitted=admitted,
        outcome=SimpleNamespace(stopped=lambda item, _stage: item),
    )

    body = response.body.decode()
    assert "needs_configuration (unpriced_model_under_cost_cap)" in body and "budget_exceeded" not in body
    assert "Runtime → Model catalog" in body


@pytest.mark.asyncio
async def test_usage_and_unpriced_policy_routes_are_admin_only(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    for path in ("/api/v1/observability/usage?window=7d", "/api/v1/admin/runtime/unpriced-model-policy"):
        assert (await call_as(client, "GET", path, viewer)).status_code == 403
        assert (await call_as(client, "GET", path, admin)).status_code == 200
    saved = await call_as(client, "PUT", "/api/v1/admin/runtime/unpriced-model-policy", admin, json={"policy": "warn"})
    assert saved.status_code == 200 and saved.json() == {"policy": "warn"}
    assert (await call_as(client, "GET", "/api/v1/observability/usage?window=year", admin)).status_code == 422
