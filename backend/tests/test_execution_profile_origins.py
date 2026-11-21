"""Every path that reaches the agent loop builds its execution profile from a declared origin (roadmap item 1).

- a turn without a profile is ``denied`` with an explicit code, and a run that declares no origin
  is ``needs_configuration``: neither is an allow;
- a sub-agent's profile derives from its parent's, tightening only;
- schedule, flow and worker runs take their profile from their governed configuration (C1).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.agent.engine as engine_module
from app.agent.core.context.run_context_routing import resolve_turn_routing_profile
from app.agent.engine._engine_product_run import ProductRunScope
from app.models import Project, Session, User
from app.models.runtime.product_run import ProductRun
from app.services.product_run.turn_outcome import gate_move
from app.services.run_capability import decide_run_capability
from app.services.run_capability.flow_capability import flow_session_capability_metadata
from app.services.run_capability.schedule_capability import schedule_session_capability_metadata
from app.services.run_capability.sub_agent_capability import sub_agent_session_capability_metadata
from app.services.run_capability.worker_profiles import worker_session_capability_metadata
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.sub_agent_group.service import _run_child_session
from app.services.worker_execution_profile import build_worker_execution_profile, worker_turn_refusal
from app.services.workflow_contracts.decisions import ALLOW_CHANGES, CAPABILITY_ESCALATION_DECISION

CHANGE_WORKFLOW = {"source": "db", "status": "matched", "workflow_contract": {"capability_class": "change"}}


async def _profile(db, metadata: dict, *, parent_session_id: str | None = None, agent_definition=None) -> dict:
    await resolve_turn_routing_profile(
        db=db,
        session_metadata=metadata,
        user_message="Summarize the open incidents.",
        agent_type="coding",
        project_id=None,
        agent_definition=agent_definition,
        runtime_target_id=None,
        parent_session_id=parent_session_id,
    )
    return metadata["execution_profile"]


async def _parent_session(db, capability_class: str) -> Session:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="diagnosis",
        metadata_={"execution_profile": {"status": "allowed", "capability": {"class": capability_class, "enforced": True}}},
    )
    db.add(parent)
    await db.flush()
    return parent


def test_a_turn_without_a_profile_is_denied_with_an_explicit_code() -> None:
    gate = evaluate_execution_gate(None)
    assert (gate.allowed, gate.status, gate.decision_source) == (False, "denied", "missing_profile")
    move = gate_move(gate, None)
    assert (move.to_state, move.end_reason) == ("denied", "gate_missing_profile")


@pytest.mark.asyncio
async def test_a_run_that_declares_no_origin_needs_configuration_instead_of_running_read_only(db) -> None:
    profile = await _profile(db, {})
    assert profile["status"] == "needs_configuration"
    assert profile["capability"]["source"] == "missing_declaration"
    gate = evaluate_execution_gate(profile)
    assert (gate.allowed, gate.status) == (False, "needs_configuration")


def test_a_child_never_exceeds_its_read_only_parent() -> None:
    capped_workflow = decide_run_capability(
        routing_resolution=CHANGE_WORKFLOW,
        requested_agent_type="coding",
        requested_mode_capability="change",
        parent_capability_class="read_only",
    )
    assert (capped_workflow.capability_class, capped_workflow.capped_by_parent) == ("read_only", True)
    assert capped_workflow.effective_agent_type == "diagnosis"
    capped_escalation = decide_run_capability(
        routing_resolution=None,
        requested_agent_type="coding",
        requested_mode_capability="change",
        parent_capability_class="read_only",
        recorded_decisions={CAPABILITY_ESCALATION_DECISION: ALLOW_CHANGES},
    )
    assert (capped_escalation.capability_class, capped_escalation.escalated) == ("read_only", False)


@pytest.mark.asyncio
async def test_a_sub_agent_profile_derives_from_its_parent_turn(db) -> None:
    parent = await _parent_session(db, "read_only")
    spawning_turn = SimpleNamespace(run_capability={"class": "read_only", "enforced": True})
    coding_definition = {"agent_type": "coding", "capability_type": "change"}

    profile = await _profile(
        db,
        sub_agent_session_capability_metadata(spawning_turn),
        parent_session_id=parent.id,
        agent_definition=coding_definition,
    )
    assert (profile["status"], profile["decision_source"]) == ("allowed", "sub_agent_parent")
    assert (profile["capability"]["class"], profile["capability"]["parent_class"]) == ("read_only", "read_only")

    # A spawning turn without an enforced class cannot bound a child: nothing runs.
    unbounded = await _profile(
        db, sub_agent_session_capability_metadata(SimpleNamespace(run_capability=None)), agent_definition=coding_definition
    )
    assert unbounded["status"] == "needs_configuration"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "source", "capability_class"),
    [
        (schedule_session_capability_metadata(SimpleNamespace(config={"capability_class": "change"})), "schedule_definition", "change"),
        (flow_session_capability_metadata({"capability_class": "change"}), "flow_definition", "change"),
        (worker_session_capability_metadata("webhook_event"), "worker_profile", "read_only"),
    ],
    ids=["schedule", "flow", "worker"],
)
async def test_schedule_flow_and_worker_profiles_come_from_their_configuration(
    db, metadata, source, capability_class
) -> None:
    profile = await _profile(db, dict(metadata))
    assert (profile["status"], profile["decision_source"]) == ("allowed", source)
    assert (profile["capability"]["class"], profile["capability"]["source"]) == (capability_class, source)
    assert evaluate_execution_gate(profile).allowed is True


def test_the_call_agent_worker_is_gated_on_its_worker_profile() -> None:
    profile = build_worker_execution_profile("call_agent", prompt="What is the status of the release?")
    assert (profile["status"], profile["decision_source"], profile["capability"]["class"]) == (
        "allowed",
        "worker_profile",
        "read_only",
    )
    assert worker_turn_refusal("call_agent", prompt="What is the status?") is None
    assert worker_turn_refusal("call_agent", prompt="").status == "needs_clarification"


@pytest.mark.asyncio
async def test_a_sub_agent_child_turn_is_bound_to_a_product_run(db, monkeypatch) -> None:
    parent = await _parent_session(db, "read_only")
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"sub-agent-runs-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    child = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis",
        metadata_={}, parent_session_id=parent.id, sub_agent_depth=1,
    )
    db.add(child)
    await db.commit()
    seen: dict = {}

    async def recording_run_agent(**kwargs):
        seen.update(kwargs)
        async with ProductRunScope(kwargs["db"], session_id=kwargs["session_id"], origin=kwargs["run_origin"]):
            pass
        return
        yield

    monkeypatch.setattr(engine_module, "run_agent", recording_run_agent)
    await _run_child_session(
        session_factory=async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False),
        group_id="group",
        parent_session_id=parent.id,
        session_id=child.id,
        task="Inspect the module.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        sub_agent_depth=1,
    )
    assert (seen["run_origin"], seen["parent_session_id"]) == ("sub_agent", parent.id)
    origins = (await db.execute(select(ProductRun.origin).where(ProductRun.session_id == child.id))).scalars().all()
    assert origins == ["sub_agent"]
