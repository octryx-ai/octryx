"""The independent reviewer runs as its own session on a model chosen per engine (node > Workspace > platform
default); ``company`` runs exactly that model, ``seat`` a tool-less device turn with a budgeted fallback."""

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
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


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
async def test_a_platform_default_the_installation_lacks_reviews_on_its_own_model_and_says_so(db, tmp_path,
                                                                                         workspace_runtimes):  # noqa: F811
    workspace_runtimes.runtimes = [_runtime("qwen3.5-9b")]
    run, _ = await _awaiting_review(db, tmp_path)
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert run.status == "completed"
    assert {model for model, _ in workspace_runtimes.called} == {"qwen3.5-9b"}
    review = run.context["review"]
    assert (review["reviewer_model"], review["reviewer_model_source"], review["reviewer_model_requested"]) == (
        "qwen3.5-9b", "installation_default", DEFAULT)


@pytest.mark.asyncio
async def test_a_model_chosen_explicitly_that_is_not_admitted_still_pauses_with_the_clear_reason(
        db, tmp_path, workspace_runtimes):  # noqa: F811
    workspace_runtimes.runtimes = [_runtime("qwen3.5-9b")]
    run, _ = await _awaiting_review(db, tmp_path, workspace_policy={"review": {"claude_code": {"model": DEFAULT}}})
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "review_no_decision")
    assert REASON_MODEL_NOT_ADMITTED in run.node_state["pause"]["message"]
    assert workspace_runtimes.called == []  # a Workspace's own choice is never replaced silently


@pytest.mark.asyncio
async def test_a_model_an_admin_added_reviews_although_the_workspace_chain_does_not_list_it(
        db, workspace_runtimes):  # noqa: F811
    provider = await _catalog_provider(db)
    workspace_runtimes.runtimes = [_runtime("stub-model")]  # the environment's model, no provider
    model = await company_review_model(db, project_id=None, model="r2-stub")
    assert [(runtime["model"], runtime["provider_id"]) for runtime in model._runtimes] == [("r2-stub", provider.id)]


@pytest.mark.asyncio
async def test_a_provider_scoped_to_another_workspace_never_serves_this_workspaces_review(db):
    import uuid

    from app.services.workflow_runs.review.model_catalog import catalog_runtimes

    own, other = (Project(id=str(uuid.uuid4()), name=f"scope-{uuid.uuid4().hex[:6]}", is_active=True, config={})
                  for _ in range(2))
    db.add_all([own, other])
    await db.flush()
    scoped = await _catalog_provider(db, project_id=other.id)
    unscoped = await _catalog_provider(db)
    for project_id in (own.id, None):
        found = await catalog_runtimes(db, project_id, "r2-stub", set())
        assert [runtime["provider_id"] for runtime in found] == [unscoped.id]
    found = await catalog_runtimes(db, other.id, "r2-stub", set())
    assert {runtime["provider_id"] for runtime in found} == {scoped.id, unscoped.id}


async def _catalog_provider(db, *, project_id: str | None = None):
    import uuid

    from app.models import LLMModel, LLMProvider

    provider = LLMProvider(name=f"bundled-{uuid.uuid4().hex[:6]}", driver="litellm", display_name="Bundled",
                           endpoint_url="http://127.0.0.1:4000/v1", is_active=True, project_id=project_id)
    db.add(provider)
    await db.flush()
    db.add(LLMModel(provider_id=provider.id, model_id="r2-stub", display_name="R2 Stub", is_active=True,
                    cleared_up_to="internal"))
    await db.flush()
    return provider
