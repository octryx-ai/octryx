"""Approval and clarification pauses, missing and malformed snapshots and the closed set of summary states."""

import pytest

from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY, build_turn_execution_snapshot
from app.services.session.turn_execution_summary import (
    SUMMARY_STATES,
    TurnApprovalEvidence,
    build_turn_execution_summary,
)
from tests.turn_execution_summary_support import (
    PROMPT,
    _evidence,
    _profile,
    _snapshot,
    _stopped_summary,
    _summary,
)


def _pending_proposal_snapshot() -> dict:
    """A turn blocked by the workflow proposal gate (``workflow_routing/proposal.py``)."""
    profile = _profile(policy={"source": "workflow_proposal", "status": "needs_confirmation"})
    return build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={
            "workflow_routing_policy_resolution": {
                "source": "workflow_proposal",
                "status": "needs_confirmation",
                "workflow_proposal": {
                    "version": "workflow_proposal.v1",
                    "status": "needs_confirmation",
                    "reason_code": "confirmation_required_change_capable",
                    "proposal_id": "proposal-1",
                    "workflow_key": "spring-boot-4-upgrade",
                    "workflow_title": "Spring Boot 4 upgrade",
                    "confidence": "high",
                    "reason": f"Model reason echoing {PROMPT}",
                    "change_capable": True,
                },
            },
        },
        agent_definition=None,
    )


def test_intermediate_trace_is_neutral_never_terminal() -> None:
    for outcome in ("finished", "failed", "cancelled"):
        summary = _summary(_snapshot(), runtime_outcome=outcome, intermediate=True)
        assert summary["state"] == "unknown"
        assert summary["state_reason"]["code"] == "intermediate_trace"
        assert summary["next_action"] == {"kind": "none", "label": None}
    pending = (TurnApprovalEvidence("a", "t", "pending"),)
    assert _summary(_snapshot(), approvals=pending, intermediate=True)["state"] == "unknown"


def test_pending_approval_without_finished_marker_is_waiting_approval() -> None:
    approvals = (TurnApprovalEvidence("appr-1", "terraform_apply", "pending"),)
    assert _summary(_snapshot(), runtime_outcome="unknown", approvals=approvals)["state"] == "waiting_approval"
    assert _summary(_snapshot(), runtime_outcome="failed", approvals=approvals)["state"] == "failed"


def test_pending_approval_is_waiting_approval() -> None:
    approvals = (TurnApprovalEvidence("appr-1", "terraform_apply", "pending", "2026-09-27T10:00:00"),)
    summary = _summary(_snapshot(), approvals=approvals)
    assert summary["state"] == "waiting_approval"
    assert summary["next_action"]["kind"] == "resolve_approval"
    assert summary["approvals"] == [
        {
            "approval_id": "appr-1",
            "tool_name": "terraform_apply",
            "status": "pending",
            "created_at": "2026-09-27T10:00:00",
            "resolved_at": None,
        }
    ]


def test_resolved_approval_turn_stays_unverified() -> None:
    approvals = (TurnApprovalEvidence("appr-1", "terraform_apply", "approved"),)
    assert _summary(_snapshot(), approvals=approvals)["state"] == "finished_unverified"


def test_unresolvable_approval_is_unknown_not_success() -> None:
    approvals = (TurnApprovalEvidence("appr-1", "terraform_apply", None),)
    summary = _summary(_snapshot(), approvals=approvals)
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "approval_state_unknown"
    assert summary["next_action"]["kind"] == "contact_administrator"
    assert summary["next_action"]["label"]


def test_clarification_pause_is_needs_clarification_from_runtime() -> None:
    summary = _summary(_snapshot(), clarification_requested=True)
    assert summary["state"] == "needs_clarification"
    assert summary["state_reason"]["source"] == "runtime"


def test_a_trace_without_snapshot_is_unknown() -> None:
    summary = _summary(None)
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "missing_snapshot"
    assert summary["execution_profile"] is None
    assert summary["agent"] == {"id": None, "name": None, "selection_source": None}


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-dict",
        {"version": "turn_execution_snapshot.v0"},
        {"version": "turn_execution_snapshot.v1", "execution_profile": {}, "gate": {"allowed": "yes"}},
        {"version": "turn_execution_snapshot.v1", "execution_profile": [], "gate": {"allowed": True}},
    ],
)
def test_malformed_snapshot_is_unknown(raw) -> None:
    summary = build_turn_execution_summary(
        _evidence(None, context_snapshot={TURN_EXECUTION_SNAPSHOT_KEY: raw})
    )
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "malformed_snapshot"


def test_allowed_gate_with_non_allowed_profile_is_inconsistent() -> None:
    snapshot = _snapshot()
    snapshot["execution_profile"]["status"] = "denied"
    summary = _summary(snapshot)
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "inconsistent_snapshot"


def test_non_dict_context_snapshot_is_legacy() -> None:
    summary = build_turn_execution_summary(_evidence(None, context_snapshot=["x"]))
    assert summary["state"] == "unknown"


def test_every_state_has_a_next_action_and_is_closed() -> None:
    observed = {
        _summary(_snapshot())["state"],
        _summary(_snapshot(_profile("denied")))["state"],
        _summary(_snapshot(_profile("needs_approval")))["state"],
        _summary(_snapshot(_profile("needs_configuration")))["state"],
        _summary(_snapshot(_profile("needs_clarification")))["state"],
        _summary(_pending_proposal_snapshot())["state"],
        # The held phased start whose Allow started its run (``phased_start``).
        _summary(_pending_proposal_snapshot(), workflow_run_started=True)["state"],
        _summary(_snapshot(_profile("weird")))["state"],
        _summary(_snapshot(), approvals=(TurnApprovalEvidence("a", "t", "pending"),))["state"],
        _summary(_snapshot(), runtime_outcome="failed")["state"],
        _summary(_snapshot(), runtime_outcome="cancelled")["state"],
        _stopped_summary("step_tool_required")["state"],
        _summary(None)["state"],
    }
    assert observed == set(SUMMARY_STATES)
