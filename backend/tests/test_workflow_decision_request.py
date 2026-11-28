"""Contract tests: a workflow clarification hands the chat UI its closed decision options."""

from __future__ import annotations

from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY, build_turn_execution_snapshot
from app.services.session.turn_execution_summary import TurnExecutionEvidence, build_turn_execution_summary
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


