"""Contract tests for workflow proposals: the platform proposes, the user confirms.

A fake provider returns the model's structured answer; the control-plane runtime list is faked,
everything else (catalog, admission boundary, capability check, execution gate, snapshot,
summary) is the real code path.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Session, TurnTrace, User
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.workflow_proposal_support import (  # noqa: F401
    MESSAGE,
    _answer,
    _profile,
    _project,
    _resolve,
    proposal_model,
)

pytestmark = pytest.mark.workflow_proposals

# A seeded published phased workflow: the only kind a proposal can name.
PHASED_WORKFLOW = "incident-analysis"


@pytest.mark.asyncio
async def test_unknown_key_is_no_proposal_never_a_guess(db, proposal_model):  # noqa: F811
    proposal_model(_answer("code-structure-diagram-routing-please"))

    resolution = await _resolve(db)

    record = resolution["workflow_proposal"]
    assert record["status"] == "none"
    assert record["reason_code"] == "unknown_key"
    assert record["workflow_key"] is None and record["proposal_id"] is None
    assert resolution["status"] == "unmatched" and resolution["workflow_id"] is None
    assert evaluate_execution_gate(_profile(resolution)).allowed is True


@pytest.mark.asyncio
async def test_phased_proposal_needs_confirmation_and_nothing_runs(db, proposal_model, monkeypatch):  # noqa: F811
    provider = proposal_model(_answer(PHASED_WORKFLOW))
    resolution = await _resolve(db)
    record = resolution["workflow_proposal"]
    assert record["status"] == "needs_confirmation"
    assert record["reason_code"] == "workflow_run_required"
    assert record["workflow_key"] == PHASED_WORKFLOW and record["change_capable"] is True
    assert resolution["workflow_id"] is None and resolution["workflow_contract"] is None
    # The proposal call saw the closed catalog and the message, as one governed dispatch.
    assert len(provider.calls) == 1 and PHASED_WORKFLOW in provider.calls[0][0]["content"]

    # Through the real runtime boundary: the gate blocks, the agent loop never dispatches.
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        agent_type="diagnosis",
        status="running",
        metadata_={ROUTING_RESOLUTION_KEY: resolution},
    )
    db.add(session)
    await db.flush()
    dispatched: list = []

    async def forbidden_dispatch(**kwargs):
        dispatched.append(kwargs)
        raise AssertionError("the agent loop must not dispatch a pending proposal")

    async def fake_engine_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "fake", "model": "fake-model"}]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_engine_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", forbidden_dispatch)
    events = [
        event
        async for event in run_agent(
            session_id=session.id, user_message=MESSAGE, user_id=user.id, project_id=None, agent_type="diagnosis", db=db
        )
    ]
    assert dispatched == []
    assert "press Start" in events[-1].content

    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().one()
    summary = await load_user_turn_execution_summary(db, user_id=user.id, trace_id=trace.id)
    assert summary["state"] == "needs_confirmation"
    assert summary["next_action"]["kind"] == "confirm_workflow_proposal"
    assert summary["workflow_proposal"]["workflow_key"] == PHASED_WORKFLOW
    # The model-written reason stays out of the closed read model.
    assert "reason" not in summary["workflow_proposal"]


@pytest.mark.asyncio
async def test_model_refusal_and_denied_admission_are_explicit_none(db, proposal_model):  # noqa: F811
    proposal_model("I can't help with choosing a workflow.")
    refused = (await _resolve(db))["workflow_proposal"]
    assert (refused["status"], refused["reason_code"]) == ("none", "model_refused")

    # A gateway runtime whose alias the Workspace does not grant: the admission boundary
    # refuses, no client is built, and the outcome names the refusal.
    project = await _project(db, {"model_policy": {}, "data_policy": {"classification": "internal"}})
    provider = proposal_model(
        _answer(PHASED_WORKFLOW),
        runtimes=[{"provider_name": "litellm", "driver": "litellm_gateway", "model": "ungranted", "target_id": "t1"}],
    )
    denied_resolution = await _resolve(db, project_id=project.id)
    denied = denied_resolution["workflow_proposal"]
    assert denied["status"] == "none"
    assert denied["reason_code"] in {"admission_denied", "admission_needs_configuration"}
    assert provider.calls == []
    assert denied_resolution["status"] == "unmatched" and denied_resolution["workflow_id"] is None


@pytest.mark.asyncio
async def test_policy_switch_turns_proposals_off(db, proposal_model):  # noqa: F811
    provider = proposal_model(_answer(PHASED_WORKFLOW))
    project = await _project(db, {"workflow_proposal_policy": {"enabled": False}})

    resolution = await _resolve(db, project_id=project.id)

    assert provider.calls == []
    assert resolution["workflow_proposal"]["status"] == "disabled"
    assert resolution["status"] == "unmatched" and resolution["workflow_id"] is None


@pytest.mark.asyncio
async def test_explicit_workflow_key_always_wins_without_a_proposal_call(db, proposal_model):  # noqa: F811
    provider = proposal_model(_answer(PHASED_WORKFLOW))

    explicit = await _resolve(db, workflow_key=PHASED_WORKFLOW)
    no_workflow = await _resolve(db, workflow_key="none")

    assert provider.calls == []
    # A phased key chosen in the composer holds the turn for its start confirmation; no proposal call is made.
    assert explicit["status"] == "needs_confirmation" and explicit["workflow_id"] is None
    assert explicit["workflow_proposal"]["reason_code"] == "explicit_phased_selection"
    assert explicit["workflow_proposal"]["workflow_key"] == PHASED_WORKFLOW
    assert no_workflow["workflow_proposal"]["reason_code"] == "user_selected_no_workflow"
    assert no_workflow["workflow_id"] is None
