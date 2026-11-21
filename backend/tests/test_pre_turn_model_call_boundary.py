"""A chat turn makes exactly one model call, on the governed runtime path.

A model call while the turn is prepared would get no guardrail scan, no budget check, no selected target, no
runtime attempt, no usage event and no trace. These tests pin the boundary:

- turn preparation never builds a provider or resolves runtimes for an explicit workflow
  selection; for a turn without ``workflow_key`` the only pre-turn call is the governed
  workflow proposal (registered dispatch owner ``workflow_proposal``, admitted,
  guardrail-scanned, bounded, recorded on the routing resolution), never an ungoverned router
- a stored routing hint from an earlier turn never decides the next turn
- a full direct-chat turn makes exactly one provider call, and that call is attempted,
  usage-accounted and traced on the same target; its trace shows the routing fields
  together (profile, policy, provider, model, target)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.models import Session as AgentSession
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.pre_turn_model_call_boundary_support import (  # noqa: F401
    FAKE_AWS_KEY,
    FAKE_EMAIL,
    SECRET_PROMPT,
    _admin,
    _first_active_target,
    provider_recorder,
    runtime_resolutions,
)
from tests.turn_preparation_support import prepare_chat_turn

pytestmark = pytest.mark.workflow_proposals


ROUTER_AUDIT_ACTIONS = {"routing.llm_router.decided", "routing.safety_gate.applied"}


async def _routing_audit_actions(db) -> set[str]:
    rows = (await db.execute(select(AuditLog).where(AuditLog.resource_type == "routing_decision"))).scalars().all()
    return {row.action for row in rows}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["direct_chat", "explicit_workflow_key", "explicit_coding_mode", "explicit_runtime_target"],
)
async def test_prepare_chat_turn_builds_no_provider_and_resolves_no_runtimes(
    db, provider_recorder, runtime_resolutions, scenario  # noqa: F811
):
    admin = await _admin(db)
    prepare_kwargs: dict = {"db": db, "user": admin, "prompt": SECRET_PROMPT, "agent_type": "diagnosis"}
    target = None
    if scenario == "explicit_workflow_key":
        # A phased workflow chosen in the composer: the turn is held for its one start confirmation.
        prepare_kwargs["workflow_key"] = "bug-fix-reproduction"
    elif scenario == "explicit_coding_mode":
        prepare_kwargs.update(agent_type="coding", agent_type_explicit=True)
    elif scenario == "explicit_runtime_target":
        target = await _first_active_target(db)
        prepare_kwargs.update(runtime_target_id=target.id, runtime_target_id_explicit=True)

    session, _runtime_target_id, _thinking_level, _agent_payload = await prepare_chat_turn(
        **prepare_kwargs
    )

    assert not (await _routing_audit_actions(db)) & ROUTER_AUDIT_ACTIONS
    proposal = session.metadata_[ROUTING_RESOLUTION_KEY].get("workflow_proposal")
    if scenario == "explicit_workflow_key":
        # An explicit selection always wins: no proposal call, no provider, no runtime resolution.
        assert provider_recorder.constructions == []
        assert provider_recorder.chat_calls == []
        assert runtime_resolutions.calls == 0
        assert (proposal["status"], proposal["reason_code"]) == ("needs_confirmation", "explicit_phased_selection")
        assert "dispatch" not in proposal or not proposal["dispatch"]
    else:
        # The only pre-turn call is the governed proposal, and the guardrails ran before it.
        assert provider_recorder.turn_calls() == []
        assert len(provider_recorder.proposal_calls()) == 1
        sent = provider_recorder.sent_text(provider_recorder.proposal_calls()[0])
        assert FAKE_EMAIL not in sent and FAKE_AWS_KEY not in sent
        # The fake answers "PONG-775", no structured answer: an explicit, recorded none.
        assert (proposal["status"], proposal["reason_code"]) == ("none", "model_refused")
        assert proposal["dispatch"]["dispatch_owner"] == "workflow_proposal"
    profile = session.metadata_["execution_profile"]
    assert profile["llm_router"] == {"status": "not_used"}
    assert "safety_plan" not in session.metadata_
    if scenario == "direct_chat":
        assert profile["decision_source"] == "direct_chat_safe"
        assert session.metadata_["routing_intent_source"] == "default"
        assert session.metadata_["routing_intent_confidence"] == 1.0
    elif scenario == "explicit_workflow_key":
        # The phased workflow never runs inside the chat turn: no workflow contract is selected for it.
        assert not session.metadata_.get("expected_workflow_id")
    elif scenario == "explicit_coding_mode":
        # Explicit mode wins; no model overrides it.
        assert profile["decision_source"] == "explicit_ui_context"
        assert session.metadata_["routing_intent"] == "coding"
        assert session.agent_type == "coding"
    else:
        assert profile["runtime"]["runtime_target_id"] == target.id


@pytest.mark.asyncio
async def test_prepare_chat_turn_clears_router_era_metadata(db, provider_recorder, runtime_resolutions):  # noqa: F811
    admin = await _admin(db)
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        agent_type="chat",
        status="active",
        metadata_={
            "safety_plan": {"tool_allowlist": ["run_shell_command"]},
            "execution_profile": {"status": "allowed", "llm_router": {"status": "selected", "reasoning": "old"}},
        },
    )
    db.add(session)
    await db.commit()

    prepared, *_ = await prepare_chat_turn(
        db=db, user=admin, prompt="Say hello in one short sentence.", session_id=session.id, agent_type="diagnosis"
    )

    assert "safety_plan" not in prepared.metadata_
    assert prepared.metadata_["execution_profile"]["llm_router"] == {"status": "not_used"}
    assert provider_recorder.turn_calls() == []
