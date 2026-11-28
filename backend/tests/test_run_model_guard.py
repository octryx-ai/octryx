"""A run's hard limits at the model gateway."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models import UsageEvent
from app.services.workflow_runs.octryx.model_guard import (
    DEFAULT_RUN_BUDGET_USD,
    EVENT_MODEL_MAPPED,
    REASON_RUN_BUDGET,
    guard_model_call,
    list_cost,
    model_tier,
    run_models,
)
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

HAIKU = "claude-haiku-5-5"


def _nodes(**models: str) -> dict:
    return {node_id: SimpleNamespace(config={"model": model}) for node_id, model in models.items()}


def test_a_model_above_the_runs_own_runs_on_the_phases_model():
    models = run_models(_nodes(implement=HAIKU), "implement")
    assert models.replacement("claude-opus-5-5") == HAIKU
    assert models.replacement("opus") == HAIKU
    assert models.replacement("claude-sonnet-5") == HAIKU
    assert models.replacement(HAIKU) is None
    assert models.replacement("claude-haiku-4-5-20251001") is None
    assert models.replacement("gpt-5.5") == HAIKU


def test_a_team_run_may_use_each_of_its_role_models_but_nothing_above():
    team = {"team": SimpleNamespace(config={"model": HAIKU, "roles": {"coordinator": {"model": "claude-sonnet-5-5"},
                                                                      "backend": {"model": HAIKU}}})}
    models = run_models(team, "team")
    assert models.replacement("claude-sonnet-5-5") is None
    assert models.replacement("claude-opus-5-5") == HAIKU


def test_a_run_without_any_model_is_not_mapped():
    assert run_models({"implement": SimpleNamespace(config={})}, "implement").replacement("claude-opus-5-5") is None


def test_list_cost_uses_the_long_context_tier_of_haiku():
    short = list_cost(HAIKU, tokens_in=1_000, tokens_out=1_000_000)
    assert short == pytest.approx(0.50 + 0.0001)
    long = list_cost(HAIKU, tokens_in=0, tokens_out=0, cache_read=200_000)
    assert long == pytest.approx(200_000 * 0.50 * 0.1 / 1_000_000)
    assert list_cost("claude-opus-5-5", tokens_in=0, tokens_out=1_000_000) == pytest.approx(20.0)


async def _haiku_run(db):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    run.context = {**dict(run.context or {}), "runtime_target": {"kind": "device", "model": HAIKU}}
    await db.flush()
    return run, await main_session_id(db, run), admin


@pytest.mark.asyncio
async def test_a_subagent_asking_for_opus_in_a_haiku_run_runs_on_haiku_and_the_run_records_it(db):
    run, session_id, _ = await _haiku_run(db)
    body = {"model": "claude-opus-5-5", "messages": [{"role": "user", "content": "build the frontend"}]}
    guarded = await guard_model_call(db, session_id, body)
    assert not guarded.refusal and guarded.body["model"] == HAIKU and guarded.body["messages"] == body["messages"]
    await db.refresh(run)
    assert run.context[EVENT_MODEL_MAPPED] == ["claude-opus-5-5"]
    assert (await guard_model_call(db, session_id, {"model": HAIKU, "messages": []})).body["model"] == HAIKU


@pytest.mark.asyncio
async def test_a_session_outside_any_run_is_unchanged(db):
    body = {"model": "claude-opus-5-5", "messages": []}
    assert (await guard_model_call(db, str(uuid.uuid4()), body)).body == body


@pytest.mark.asyncio
async def test_a_run_past_its_budget_pauses_and_refuses_every_further_call(db):
    run, session_id, admin = await _haiku_run(db)
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session_id, user_id=admin.id, provider="anthropic",
                      model=HAIKU, tokens_in=1_000, tokens_out=10_000_000, cost=5))
    await db.flush()
    guarded = await guard_model_call(db, session_id, {"model": HAIKU, "messages": []})
    assert guarded.refusal == REASON_RUN_BUDGET and "paused" in guarded.hint
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "budget_limit")
    pause = run.node_state["pause"]
    assert pause["keys"] == ["cost_usd"] and pause["budget_usd"] == DEFAULT_RUN_BUDGET_USD
    assert pause["spent_usd"] > DEFAULT_RUN_BUDGET_USD and "Continue with more budget" in pause["message"]
    assert run.limits["budget_ceiling"]["cost_usd"] == DEFAULT_RUN_BUDGET_USD * 3
    again = await guard_model_call(db, session_id, {"model": HAIKU, "messages": []})
    assert again.refusal == REASON_RUN_BUDGET


@pytest.mark.asyncio
async def test_the_seat_route_refuses_a_run_past_its_budget_with_the_reason(db):
    from app.services.model_gateway.inbound.refusals import InboundRefusal
    from app.services.model_gateway.inbound.run_limits import run_limited_body

    run, session_id, admin = await _haiku_run(db)
    run.limits = {**dict(run.limits or {}), "budget": {"cost_usd": 0.01}}
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session_id, user_id=admin.id, provider="anthropic",
                      model=HAIKU, tokens_in=100_000, tokens_out=100_000, cost=0.02))
    await db.flush()
    refused = await run_limited_body(db, session_id, {"model": HAIKU, "messages": []})
    assert isinstance(refused, InboundRefusal)
    assert (refused.reason, refused.http_status) == (REASON_RUN_BUDGET, 403) and "$0.01" in refused.hint


@pytest.mark.asyncio
async def test_a_seat_calls_list_price_equivalent_only_warns_and_never_pauses_the_run(db):
    from sqlalchemy import select

    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.octryx.model_guard import EVENT_SEAT_EQUIVALENT

    run, session_id, admin = await _haiku_run(db)
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session_id, user_id=admin.id, provider="anthropic_seat",
                      model=HAIKU, tokens_in=1_000, tokens_out=10_000_000, cost=0))
    await db.flush()
    for _ in range(2):
        guarded = await guard_model_call(db, session_id, {"model": HAIKU, "messages": []})
        assert not guarded.refusal
    await db.refresh(run)
    assert run.status != "paused" and run.budget_usage["list_cost_usd"] > DEFAULT_RUN_BUDGET_USD
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                              WorkflowRunEvent.kind == EVENT_SEAT_EQUIVALENT))).scalars()
    assert len(list(events)) == 1


# A Codex seat request (gpt-6-luna) compared with the Claude phase model would send claude-haiku-5-5 to ChatGPT and
# fail every Codex seat turn. Codex models are only compared with Codex models.
@pytest.mark.parametrize("phase_model", ["claude-sonnet-5-5", "claude-haiku-5-5"])
@pytest.mark.parametrize("requested", ["gpt-6-luna", "gpt-6.1-sol"])
def test_a_codex_seat_turn_in_a_claude_phase_runs_its_own_model(phase_model, requested):
    models = run_models(_nodes(draft=phase_model, review="claude-haiku-5-5"), "draft")
    assert models.replacement(requested, engine="codex") is None


def test_a_codex_model_above_the_runs_codex_model_runs_on_it_and_never_on_a_claude_model():
    models = run_models(_nodes(implement="claude-haiku-5-5"), "implement", target_model="gpt-6.1-sol")
    assert models.replacement("gpt-6-astra", engine="codex") == "gpt-6.1-sol"
    assert models.replacement("gpt-6-luna", engine="codex") is None
    assert models.replacement("gpt-6.1-sol", engine="codex") is None
    assert models.replacement("claude-opus-5-5") == "claude-haiku-5-5"


def test_codex_models_count_for_the_budget():
    assert list_cost("gpt-6-luna", tokens_in=200_000, tokens_out=0) == pytest.approx(0.02)
    assert list_cost("gpt-6-luna", tokens_in=1_000_000, tokens_out=0) == pytest.approx(0.20)
    assert list_cost("gpt-6.1-sol", tokens_in=0, tokens_out=1_000_000) == pytest.approx(10.0)
    assert model_tier("gpt-6.1-sol") is None and model_tier("claude-sonnet-5-5") == 2
