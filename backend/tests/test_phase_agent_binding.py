"""The phase names its agent; slices inherit it; the review node runs as the Reviewer."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AgentDefinition, UsageEvent
from app.services.platform_agents.catalog import ENGINEER, REVIEWER
from app.services.session.agent_selection_sources import AgentSelectionSource
from app.services.session.turn_agent_selection import select_turn_agent
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.records import WorkflowRunError, new_chat_session, start_run
from app.services.workflow_runs.review.reviewer_agent import ReviewerSetup, order_review_runtimes
from app.services.workflow_runs.review.runner import run_due_reviews
from app.services.workflow_runs.slices.rules import sub_agent_config
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.platform_agent_publish_support import draft_edit, publish_edit
from tests.test_workflow_run_pause import _turn
from tests.workflow_run_review_support import PASS, ScriptedReviewer, _reviewed_definition, changed_repo

pytestmark = pytest.mark.asyncio


def _with_agent(definition: dict, agent: str | None, **extra) -> dict:
    definition = copy.deepcopy(definition)
    for node in definition["nodes"]:
        if node["type"] == "phase":
            if agent is not None:
                node["config"]["agent"] = agent
            node["config"].update(extra)
    return definition


def _codes(definition: dict) -> set[str]:
    return {error["code"] for error in validate_phased_definition(definition)["errors"]}


async def _agent(db, key: str) -> AgentDefinition:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()


async def test_publish_refuses_unknown_agents_a_ceiling_below_the_class_and_a_review_agent():
    assert "phase_agent_unknown" in _codes(_with_agent(phased_definition(), "coding"))
    change = _with_agent(phased_definition(), "assistant")
    change["nodes"][1]["config"]["workflow_contract"]["capability_class"] = "change"
    assert "phase_agent_ceiling" in _codes(change)
    reviewed = _with_agent(_reviewed_definition(), "assistant")
    reviewed["nodes"][2]["config"] = {"agent": "engineer"}
    assert "review_agent_fixed" in _codes(reviewed)
    mismatch = _with_agent(phased_definition(), "assistant", sub_agents={"agent": "coding"})
    assert "sub_agent_mismatch" in _codes(mismatch)
    assert validate_phased_definition(_with_agent(phased_definition(), "assistant"))["valid"]
    # A phase without an agent is refused at publish.
    without = phased_definition()
    del without["nodes"][1]["config"]["agent"]
    assert "phase_without_agent" in _codes(without)


async def test_publish_and_run_start_refuse_a_retired_phase_agent(db):
    key = await publish_phased(db, _with_agent(phased_definition(), "assistant"))
    row = await _agent(db, "assistant")
    row.retired_at, row.is_active = utc_now(), False
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await publish_phased(db, _with_agent(phased_definition(), "assistant"))
    assert refused.value.status_code == 422
    assert "phase_agent_unavailable" in {error["code"] for error in refused.value.detail["errors"]}
    admin = await admin_user(db)
    with pytest.raises(WorkflowRunError) as not_started:
        workspace_id = await run_workspace(db, admin)
        await start_run(db, user=admin, workflow_key=key,
                        project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    assert not_started.value.code == "phase_agent_unavailable"


async def test_a_phase_turn_runs_as_the_phase_agent_whatever_the_user_picked(db):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    await start_run(db, user=admin, workflow_key=await publish_phased(db, _with_agent(phased_definition(), "engineer")),
                    project_id=workspace_id,
                    session=session)
    resolution = await run_turn_resolution(db, session, user_message="Work on it.")
    engineer = await _agent(db, ENGINEER)
    assert {key: resolution["phase_agent"][key] for key in ("key", "definition_id")} == {
        "key": "engineer", "definition_id": engineer.id}
    assert resolution["phase_agent"]["revision_id"]  # AFS-1: the published revision it runs
    # The Engineer prefers a coding runtime: the phase now requires one.
    assert resolution["workflow_contract"]["required_model_capability"] == "coding"
    other = await _agent(db, "assistant")
    choice = await select_turn_agent(
        db, owner_id=admin.id, agent_id=other.id, agent_type_explicit=False, clean_prompt="Work on it.",
        session=session, routing=SimpleNamespace(policy_resolution=resolution),
        workspace_execution_view=None, project_id=None)
    assert (choice.agent_id, choice.selection_source) == (engineer.id, AgentSelectionSource.WORKFLOW_PHASE)
    assert choice.payload["builtinKey"] == "engineer" and choice.payload["capabilityCeiling"] == "change"


async def test_a_run_pinned_to_a_version_without_agents_holds_needs_configuration(db):
    # A run pinned to a version whose phases name no agent holds.
    from app.models import WorkflowRun
    from app.models.runtime.flow_definition import FlowDefinitionVersion

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=session)
    version = await db.get(FlowDefinitionVersion, (await db.get(WorkflowRun, run.id)).flow_definition_version_id)
    pinned = copy.deepcopy(version.definition_json)
    del pinned["nodes"][1]["config"]["agent"]
    version.definition_json = pinned
    await db.flush()
    resolution = await run_turn_resolution(db, session, user_message="Work on it.")
    assert (resolution["status"], resolution["profile_status"]) == ("held", "needs_configuration")
    assert "phase_without_agent" in resolution["unmatched_reason"]


async def test_slice_children_default_to_the_phase_agent():
    assert sub_agent_config({"agent": "engineer", "sub_agents": {"max_parallel": 2}})["agent"] == "engineer"
    assert sub_agent_config({"sub_agents": {}})["agent"] == ""  # N10: no built-in default; publish needs an agent


async def _review_run(db, tmp_path):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, session=session,
                          workflow_key=await publish_phased(db, _with_agent(_reviewed_definition(), "assistant")),
                          project_id=workspace_id)
    db.add(UsageEvent(session_id=session.id, user_id=admin.id, provider="p", model="author-model", tokens_in=1,
                      tokens_out=1))
    await db.commit()
    await _turn(db, session.id, ["knowledge_search"])
    return run, session


async def test_the_review_runs_as_the_reviewer_agent_with_the_author_model_recorded(db, tmp_path):
    run, _session = await _review_run(db, tmp_path)
    reviewer_row = await _agent(db, REVIEWER)
    approved = reviewer_row.system_prompt
    # A live edit is a draft and never runs; only the four-eyes published revision does.
    await draft_edit(db, reviewer_row, instructions=approved + "\nUnpublished marker.")
    await publish_edit(db, reviewer_row, instructions=approved + "\nReviewer agent marker.")
    await draft_edit(db, reviewer_row, instructions=approved + "\nLater unpublished marker.")
    await db.commit()
    scripted = ScriptedReviewer(PASS)
    assert await run_due_reviews(db, model_factory=scripted.factory) == 1
    system, _task = scripted.tasks[0]
    assert "Reviewer agent marker." in system and '"verdict"' in system
    assert "unpublished marker" not in system.lower()
    assert isinstance(scripted.reviewer, ReviewerSetup)
    assert (scripted.reviewer.definition_id, scripted.reviewer.author_model) == (reviewer_row.id, "author-model")
    await db.refresh(run)
    assert run.context["review"]["reviewer_agent"] == reviewer_row.id


async def test_reviewer_runtimes_avoid_the_author_model_unless_it_is_the_only_one():
    setup = ReviewerSetup(definition_id="r", instructions="", runtime_preference="coding", author_model="a")
    author = {"model": "a", "use_case_tags": ["coding"]}
    other = {"model": "b", "use_case_tags": []}
    assert order_review_runtimes([author, other], setup) == ([other, author], False)  # the author last, not dropped
    assert order_review_runtimes([author], setup) == ([author], True)
    assert order_review_runtimes([author, other], None) == ([author], False)  # without a setup: coding-tagged first


async def test_the_session_records_the_phase_agent(db, monkeypatch):
    from app.services.session.turn_session_record import _turn_metadata

    engineer = await _agent(db, ENGINEER)
    facts = SimpleNamespace(
        thinking_level="light", execution_profile={}, workspace_execution_view=None,
        runtime=SimpleNamespace(runtime_target_id="", runtime_label="", source=SimpleNamespace(value="default")),
        agent=SimpleNamespace(selection_source=AgentSelectionSource.WORKFLOW_PHASE,
                              resolution=SimpleNamespace(definition_id=engineer.id, revision_number=1),
                              payload={"name": "Engineer", "builtinKey": "engineer"}),
        routing=SimpleNamespace(strategy_decision=SimpleNamespace(routing_intent_confidence=None,
                                                                  routing_intent_source=""),
                                routing_intent="", routing_reason="", execution_strategy="",
                                execution_strategy_reason="", expected_workflow_id="", policy_resolution={},
                                research_policy_resolution={}))
    import app.services.session.turn_session_record as record

    monkeypatch.setattr(record, "resolution_metadata", lambda resolution: {record.RESOLUTION_METADATA_KEY: {}})
    metadata = _turn_metadata(facts)
    assert (metadata["agent_selection_source"], metadata["agent_key"], metadata["agent_revision"]) == (
        "workflow_phase", "engineer", 1)
