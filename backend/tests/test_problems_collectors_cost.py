"""The budget and unpriced model collectors (a block wins over a warning, the period follows the collect time) and stable, bounded problem keys."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import BudgetAlert, BudgetPolicy, LLMModel, LLMProvider
from app.services.problems import budgets, models_unpriced
from app.services.problems.model import CollectContext, problem_key
from tests.problems_collectors_support import NOW, _by_object, _setup, uid


@pytest.mark.asyncio
async def test_budget_block_wins_over_warning_and_old_periods_drop(db):
    project, _, ctx = await _setup(db)
    daily = BudgetPolicy(id=uid(), name="Daily cap", project_id=project.id, reset_period="daily",
                         daily_cost_limit=10, is_active=True)
    db.add(daily)
    await db.flush()
    for metric, level, when in (("cost", "warning", NOW), ("cost", "block", NOW), ("tokens", "warning", NOW),
                                ("requests", "block", NOW - timedelta(days=3))):
        db.add(BudgetAlert(policy_id=daily.id, project_id=project.id, metric_name=metric, threshold_level=level,
                           current_value=1, limit_value=1, percent_used=100, created_at=when))
    await db.flush()

    problems = {item.reason_code: item for item in await budgets.collect(db, ctx)}

    assert set(problems) == {"block_cost", "warning_tokens"}
    assert problems["block_cost"].severity == "problem" and problems["warning_tokens"].severity == "attention"
    assert problems["block_cost"].fix["href"] == "/chat?area=admin&tab=runtimeLimits"


@pytest.mark.asyncio
async def test_budget_period_follows_the_collect_time_not_the_wall_clock(db):
    # A gate started before midnight UTC can run this collector after it; the daily window must not come from the
    # wall clock while the alerts and ctx.now are from the day before, or current alerts are dropped.
    project, _, _ = await _setup(db)
    then = NOW - timedelta(days=2)
    daily = BudgetPolicy(id=uid(), name="Daily cap", project_id=project.id, reset_period="daily",
                         daily_cost_limit=10, is_active=True)
    db.add(daily)
    await db.flush()
    db.add(BudgetAlert(policy_id=daily.id, project_id=project.id, metric_name="cost", threshold_level="block",
                       current_value=1, limit_value=1, percent_used=100, created_at=then))
    await db.flush()

    ctx = CollectContext(now=then, workspace_ids=frozenset({project.id}))
    assert {item.reason_code for item in await budgets.collect(db, ctx)} == {"block_cost"}


def test_keys_are_stable_and_bounded():
    assert problem_key("run", "abc", "failed") == problem_key("run", "abc", "failed") == "run:abc:failed"
    long_key = problem_key("rule_denial", "r" * 300, "denied")
    assert long_key == problem_key("rule_denial", "r" * 300, "denied") and len(long_key) <= 200


@pytest.mark.asyncio
async def test_an_unpriced_model_of_a_platform_billed_provider_needs_attention(db):
    _, _, ctx = await _setup(db)
    billed = LLMProvider(name=f"bedrock-{uid()[:6]}", driver="bedrock_api", is_active=True, is_global=True)
    local = LLMProvider(name=f"ollama-{uid()[:6]}", driver="ollama", runtime_kind="local", is_active=True,
                        is_global=True)
    db.add_all([billed, local])
    await db.flush()
    unpriced = LLMModel(provider_id=billed.id, model_id="claude-x", display_name="Claude X", is_active=True)
    priced = LLMModel(provider_id=billed.id, model_id="claude-y", is_active=True, pricing_input=3.0,
                      pricing_output=15.0)
    half = LLMModel(provider_id=billed.id, model_id="claude-z", is_active=True, pricing_input=3.0)
    off = LLMModel(provider_id=billed.id, model_id="claude-off", is_active=False)
    free = LLMModel(provider_id=local.id, model_id="llama", is_active=True)
    db.add_all([unpriced, priced, half, off, free])
    await db.flush()

    everything = await models_unpriced.collect(db, CollectContext(now=NOW))
    found = {item.object_id for item in everything}
    assert unpriced.id in found and half.id in found
    assert not found & {priced.id, off.id, free.id}
    item = _by_object(everything, unpriced.id)[0]
    assert (item.kind, item.severity, item.object_type, item.workspace_id) == ("budget", "attention", "model", None)
    assert item.title == "Model Claude X has no price – costs are not counted."
    assert item.fix["href"] == f"/chat?area=admin&tab=modelCatalog&model={unpriced.id}"
    assert not await models_unpriced.collect(db, ctx)  # platform-wide: not in a Workspace-only scope
