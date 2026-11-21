"""Contract tests: a workflow clarification hands the chat UI its closed decision options.

The loop persists a structured decision request on the clarification message's trace
(``raw_output.workflow_decision_request``), and the turn execution summary re-derives the
options from the closed decision catalog, so the client never parses the message text and a
stored request can never inject its own options or labels.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.turn_execution_binding import bind_turn_execution_snapshot, clear_turn_execution_snapshot
from app.agent.engine._turn_tools_persistence import persist_synthesized_tool_assistant
from app.models import Session, TurnTrace, User
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY, build_turn_execution_snapshot
from app.services.session.turn_execution_summary import TurnExecutionEvidence, build_turn_execution_summary
from app.services.session.turn_execution_summary_service import load_user_turn_execution_summary
from app.services.workflow_contracts.decisions import CAPABILITY_ESCALATION_DECISION

_OPTIONS = [
    {"value": "allow_changes", "label": "Allow changes in this session"},
    {"value": "stay_read_only", "label": "Stay read-only"},
]


def _allowed_snapshot() -> dict:
    profile = {
        "version": "execution_profile.v1",
        "status": "allowed",
        "profile_id": "workflow:coding_change_tdd",
        "decision_source": "explicit_workflow_key",
        "execution_strategy": "workflow",
    }
    return build_turn_execution_snapshot(
        execution_profile=profile, gate=evaluate_execution_gate(profile), session_metadata={}, agent_definition=None
    )


def test_summary_re_derives_options_and_ignores_forged_or_intermediate_requests() -> None:
    def _summary(request, **overrides):
        evidence = TurnExecutionEvidence(
            trace_id="t1",
            session_id="s1",
            message_id="m1",
            provider="p",
            model="m",
            context_snapshot={TURN_EXECUTION_SNAPSHOT_KEY: _allowed_snapshot()},
            runtime_outcome="unknown",
            decision_request=request,
            **overrides,
        )
        return build_turn_execution_summary(evidence)

    forged = {"decision_key": CAPABILITY_ESCALATION_DECISION, "options": [{"value": "rm -rf", "label": "x"}]}
    summary = _summary(forged)
    assert summary["state"] == "needs_clarification"
    assert summary["state_reason"]["code"] == "workflow_decision_requested"
    assert summary["next_action"]["kind"] == "provide_clarification"
    assert summary["decision_request"] == {
        "decision_key": CAPABILITY_ESCALATION_DECISION,
        "options": _OPTIONS,
        "recorded_value": None,
    }
    assert _summary({"decision_key": "unknown_decision"})["decision_request"] is None
    assert _summary({"decision_key": "unknown_decision"})["state"] == "unknown"
    assert _summary(forged, intermediate=True)["decision_request"] is None


@pytest.mark.asyncio
async def test_persisted_clarification_trace_reaches_the_owner_summary(db) -> None:
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id, agent_type="coding", status="running", metadata_={})
    db.add(session)
    await db.flush()
    bind_turn_execution_snapshot(session.id, _allowed_snapshot())
    try:
        message = await persist_synthesized_tool_assistant(
            db=db,
            session_id=session.id,
            runtime={"provider_name": "copilot", "model": "m"},
            response={},
            request_messages=[],
            context_snapshot={},
            tool_results=[],
            current_user_message="Edit the file.",
            content="Please record one decision.",
            source="capability_escalation_clarification",
            assistant_content="",
            workflow_decision_request={"decision_key": CAPABILITY_ESCALATION_DECISION},
        )
    finally:
        clear_turn_execution_snapshot(session.id)
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.message_id == message.id))).scalar_one()

    summary = await load_user_turn_execution_summary(db, user_id=user.id, trace_id=trace.id)

    assert summary is not None and summary["state"] == "needs_clarification"
    assert [option["value"] for option in summary["decision_request"]["options"]] == [
        "allow_changes",
        "stay_read_only",
    ]
