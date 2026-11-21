"""Contract tests for the pure turn execution summary builder and snapshot projection."""

import json

import pytest

from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary import TURN_EXECUTION_SUMMARY_VERSION, runtime_outcome_from_trace
from tests.turn_execution_summary_support import SECRET, _profile, _snapshot, _summary


def _marked(snapshot: dict) -> dict:
    return {TURN_EXECUTION_SNAPSHOT_KEY: {**snapshot, RUNTIME_OUTCOME_KEY: RUNTIME_OUTCOME_FINISHED}}


def test_allowed_finished_turn_is_unverified_never_completed() -> None:
    summary = _summary(_snapshot())
    assert summary["version"] == TURN_EXECUTION_SUMMARY_VERSION
    assert summary["state"] == "finished_unverified"
    assert summary["state_reason"]["code"] == "runtime_finished"
    assert summary["next_action"] == {"kind": "none", "label": None}
    assert summary["run_identity"] == {
        "kind": "compat_turn",
        "product_run_id": None,
        "run_state": None,
        "attempt": None,
    }
    assert summary["execution_profile"] == {
        "version": "execution_profile.v1",
        "profile_id": "workflow:aws_evidence",
        "status": "allowed",
        "decision_source": "explicit_workflow_key",
        "workflow_key": "aws-evidence",
        "execution_strategy": "workflow",
        # A profile without a run capability section projects closed.
        "capability": {
            "class": "unknown",
            "source": None,
            "enforced": False,
            "escalated": False,
            "agent_type_ignored": False,
        },
        "tool_surface": {"source": "governed_default", "set": "diagnosis.v2"},
        "gate": {"outcome": "allowed", "status": "allowed", "decision_source": "execution_profile"},
    }
    assert summary["agent"] == {"id": "agent-1", "name": "Cloud Reviewer", "selection_source": "explicit"}
    assert summary["model"] == {"provider": "openrouter", "model": "stepfun/step-3.5-flash:free"}
    assert summary["usage"] == {"tokens_in": 12, "tokens_out": 5}


@pytest.mark.parametrize(
    ("status", "next_kind"),
    [
        ("denied", "contact_administrator"),
        ("needs_approval", "contact_administrator"),
        ("needs_configuration", "complete_configuration"),
        ("needs_clarification", "provide_clarification"),
    ],
)
def test_gate_blocked_states_map_one_to_one(status: str, next_kind: str) -> None:
    summary = _summary(_snapshot(_profile(status)), provider="execution-gate", model="")
    assert summary["state"] == status
    assert summary["state_reason"] == {
        "code": f"gate_{status}",
        "source": "execution_gate",
        "text": summary["state_reason"]["text"],
    }
    assert summary["next_action"]["kind"] == next_kind
    assert summary["execution_profile"]["gate"]["outcome"] == "blocked"
    assert summary["model"] == {"provider": None, "model": None}


@pytest.mark.parametrize("profile", [None, {"status": "brand_new_state"}, {"reason": "no status"}, "allowed"])
def test_missing_or_unknown_profile_is_blocked_unknown(profile) -> None:
    snapshot = build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={},
        agent_definition=None,
    )
    summary = _summary(snapshot)
    assert summary["state"] == "blocked_unknown"
    assert summary["next_action"]["kind"] == "contact_administrator"
    assert summary["execution_profile"]["status"] == "unknown"


def test_gate_needs_approval_never_points_at_a_nonexistent_pending_approval() -> None:
    summary = _summary(_snapshot(_profile("needs_approval")), provider="execution-gate", model="")
    assert summary["state"] == "needs_approval"
    assert summary["approvals"] == []
    assert summary["next_action"]["kind"] != "resolve_approval"
    assert "pending" not in summary["next_action"]["label"].lower()
    assert "no approval request was created" in summary["next_action"]["label"]


def test_runtime_failure_is_failed_without_raw_error() -> None:
    raw_output = {"error": f"Provider exploded: Authorization: Bearer {SECRET}"}
    outcome = runtime_outcome_from_trace({}, raw_output)
    summary = _summary(_snapshot(), runtime_outcome=outcome, provider="runtime-fallback", model="unresolved")
    assert summary["state"] == "failed"
    assert summary["next_action"]["kind"] == "retry"
    assert SECRET not in json.dumps(summary)
    assert "exploded" not in json.dumps(summary)


def test_cancelled_runtime_outcome_is_cancelled() -> None:
    # Builder contract only: no runtime producer writes ``cancelled`` yet (see
    # test_cancelled_marker_has_no_producer_and_reads_unknown).
    summary = _summary(_snapshot(), runtime_outcome="cancelled")
    assert summary["state"] == "cancelled"


def test_cancelled_marker_has_no_producer_and_reads_unknown() -> None:
    snapshot = {**_snapshot(), RUNTIME_OUTCOME_KEY: "cancelled"}
    assert runtime_outcome_from_trace({TURN_EXECUTION_SNAPSHOT_KEY: snapshot}, {"content": "x"}) == "unknown"


@pytest.mark.parametrize("outcome", ["", "completed", "passed", None])
def test_unknown_runtime_outcome_never_becomes_success(outcome) -> None:
    summary = _summary(_snapshot(), runtime_outcome=outcome)
    assert summary["state"] == "unknown"


def test_runtime_outcome_requires_an_explicit_marker() -> None:
    unmarked = {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()}
    # No error and no marker is not "finished": completion text proves nothing.
    assert runtime_outcome_from_trace(unmarked, {"content": "Task completed successfully!"}) == "unknown"
    assert runtime_outcome_from_trace(_marked(_snapshot()), {"content": "Pong"}) == "finished"
    assert runtime_outcome_from_trace(_marked(_snapshot()), {"error": "boom"}) == "failed"
    assert runtime_outcome_from_trace(unmarked, {"error": "boom"}) == "failed"
    assert runtime_outcome_from_trace(unmarked, "not a dict") == "unknown"
    # A trace without a snapshot can never carry the marker.
    assert runtime_outcome_from_trace({}, {"content": "done"}) == "unknown"
    assert runtime_outcome_from_trace({RUNTIME_OUTCOME_KEY: "finished"}, {"content": "done"}) == "unknown"


@pytest.mark.parametrize(
    "raw_output",
    [
        {"content": "stalled", "stalled_after_tool_loop": True},
        {"content": "dup", "suppressed_as_duplicate_no_tool_response": True},
        {"content": "blocked", "completion_blocker": {"code": "delivery_gate"}},
    ],
)
def test_unmarked_stall_suppression_and_blocker_exits_are_never_finished(raw_output) -> None:
    context = {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()}
    outcome = runtime_outcome_from_trace(context, raw_output)
    summary = _summary(_snapshot(), runtime_outcome=outcome)
    assert outcome == "unknown"
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "runtime_outcome_unknown"
