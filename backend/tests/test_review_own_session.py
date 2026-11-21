"""The independent reviewer runs as its own session on a configurable model.

Locally the only admitted runtime was a 9B Qwen stub: the reviewer ran on it, timed out and distorted every
measurement. Now the reviewer's model and route are chosen per engine (node > Workspace > platform default
``review_models.json``: ``claude-sonnet-5-5`` / ``gpt-6.1-terra``), ``company`` runs exactly that model or gives no verdict, and ``seat`` is a
separate tool-less device turn on the person's own subscription with a visible, budgeted company fallback.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, UsageEvent
from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.review_keys import ReviewPolicyError, normalize_review_section
from app.services.workflow_runs.review.choice import review_choice
from app.services.workflow_runs.review.model import (
    REASON_MODEL_NOT_ADMITTED,
    ReviewModelUnavailableError,
    company_review_model,
)
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.review_own_session_support import (  # noqa: F401
    DEFAULT,
    HAIKU,
    TERRA,
    _awaiting_review,
    _codex_policy,
    _runtime,
    workspace_runtimes,
)

# --- configuration ---------------------------------------------------------------------------------------------


def test_the_workspace_review_section_is_per_engine_and_never_mixes_families():
    assert normalize_review_section({"claude_code": {"model": HAIKU, "route": "seat"}, "codex": {"model": TERRA}},
                                    "p") == {"claude_code": {"model": HAIKU, "route": "seat"}, "codex": {"model": TERRA}}
    for bad, reason in (({"codex": {"model": HAIKU}}, "review_model_wrong_engine_family"),
                        ({"claude_code": {"model": TERRA}}, "review_model_wrong_engine_family"),
                        ({"claude_code": {"model": "qwen3.5-9b", "route": "seat"}}, "review_model_not_on_seat"),
                        ({"claude_code": {"route": "bedrock"}}, "invalid_route"),
                        ({"gemini": {"model": "x"}}, "unknown_engine"),
                        ({"claude_code": {"model": HAIKU, "budget": 1}}, "unknown_field")):
        with pytest.raises(ReviewPolicyError) as error:
            normalize_review_section(bad, "p")
        assert error.value.reason == reason
    # A local model is allowed when named, on the company route.
    assert normalize_review_section({"claude_code": {"model": "qwen3.5-9b"}}, "p") == {
        "claude_code": {"model": "qwen3.5-9b"}}
    assert normalize_agent_gateway_policy({"review": {"codex": {"model": TERRA, "route": "company"}}})["review"] == {
        "codex": {"model": TERRA, "route": "company"}}
    with pytest.raises(AgentGatewayPolicyError):
        normalize_agent_gateway_policy({"review": {"codex": {"model": HAIKU}}})


@pytest.mark.asyncio
async def test_node_beats_workspace_beats_platform_and_the_route_follows_the_run(db, tmp_path):
    run, _ = await _awaiting_review(db, tmp_path, workspace_policy={"review": {"claude_code": {"model": "claude-sonnet-5-5"}}})
    choice = await review_choice(db, run, {})
    assert (choice.engine, choice.model, choice.model_source) == ("claude_code", "claude-sonnet-5-5", "workspace")
    assert (choice.route, choice.route_source) == ("company", "run")  # a server run reviews on a company model
    node = await review_choice(db, run, {"model": "claude-opus-5-5"})
    assert (node.model, node.model_source) == ("claude-opus-5-5", "node")
    run.project_id = None
    platform = await review_choice(db, run, {})
    assert (platform.model, platform.model_source) == (DEFAULT, "platform")

    run.context = {**dict(run.context or {}), "runtime_target": {"kind": "device", "device_id": "d", "folder": "/f",
                                                                 "profile": "seat"}}
    seat = await review_choice(db, run, {})
    assert (seat.route, seat.route_source) == ("seat", "run")  # a seat run reviews on the seat
    assert (await review_choice(db, run, {"route": "company"})).route == "company"
    local = await review_choice(db, run, {"model": "qwen3.5-9b"})  # named explicitly: only a company runtime has it
    assert (local.model, local.route) == ("qwen3.5-9b", "company")
    assert await review_choice(db, run, {"model": "qwen3.5-9b", "route": "seat"}) == \
        "needs_configuration:review_config_invalid"


@pytest.mark.asyncio
async def test_a_codex_run_is_reviewed_by_a_codex_model_never_a_claude_one(db, tmp_path):
    run, _ = await _awaiting_review(db, tmp_path, workspace_policy=_codex_policy())
    # The shipped seeds name claude-haiku-5-5 on review nodes: it counts for Claude Code runs only.
    choice = await review_choice(db, run, {"model": HAIKU})
    assert (choice.engine, choice.model, choice.model_source) == ("codex", TERRA, "platform")
    per_engine = await review_choice(db, run, {"model": HAIKU, "reviewer": {"codex": {"model": "gpt-6-terra"}}})
    assert (per_engine.model, per_engine.model_source) == ("gpt-6-terra", "node")
    project = await db.get(Project, run.project_id)
    project.config = {"agent_gateway_policy": _codex_policy({"codex": {"model": "gpt-6-sol", "route": "seat"}})}
    await db.flush()
    workspace = await review_choice(db, run, {"model": HAIKU})
    assert (workspace.model, workspace.route, workspace.route_source) == ("gpt-6-sol", "seat", "workspace")


# --- company route ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_runs_exactly_the_chosen_model_or_says_it_is_not_admitted(db, workspace_runtimes):  # noqa: F811
    model = await company_review_model(db, project_id=None, model=DEFAULT)
    assert [runtime["model"] for runtime in model._runtimes] == [DEFAULT]  # the Qwen runtime is never a fallback
    workspace_runtimes.runtimes = [_runtime("qwen3.5-9b")]
    with pytest.raises(ReviewModelUnavailableError) as error:
        await company_review_model(db, project_id=None, model=DEFAULT)
    assert error.value.reason == REASON_MODEL_NOT_ADMITTED
    named = await company_review_model(db, project_id=None, model="qwen3.5-9b")  # only when explicitly chosen
    assert [runtime["model"] for runtime in named._runtimes] == ["qwen3.5-9b"]


@pytest.mark.asyncio
async def test_by_default_the_review_runs_on_the_platform_default_and_not_on_another_admitted_runtime(db, tmp_path,
                                                                                       workspace_runtimes):  # noqa: F811
    workspace_runtimes.runtimes = [_runtime("qwen3.5-9b"), _runtime(DEFAULT, provider_name="bedrock")]
    run, _ = await _awaiting_review(db, tmp_path)
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert run.status == "completed"
    assert {model for model, _ in workspace_runtimes.called} == {DEFAULT}
    review = run.context["review"]
    assert (review["reviewer_model"], review["reviewer_model_source"], review["reviewer_route_used"]) == (
        DEFAULT, "platform", "company")
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.dispatch_owner == "workflow_run_review"))).scalar_one()
    assert (usage.model, usage.provider, usage.tokens_in) == (DEFAULT, "bedrock", 120)


@pytest.mark.asyncio
async def test_company_with_no_runtime_serving_the_model_pauses_with_the_clear_reason(db, tmp_path,
                                                                                    workspace_runtimes):  # noqa: F811
    workspace_runtimes.runtimes = [_runtime("qwen3.5-9b")]
    run, _ = await _awaiting_review(db, tmp_path)
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "review_no_decision")
    assert REASON_MODEL_NOT_ADMITTED in run.node_state["pause"]["message"]
    assert workspace_runtimes.called == []  # nothing ran on the Qwen stub
