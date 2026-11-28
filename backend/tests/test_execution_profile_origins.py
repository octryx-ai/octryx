"""Every path that reaches the agent loop builds its execution profile from a declared origin (roadmap item 1)."""

from __future__ import annotations

from app.services.product_run.turn_outcome import gate_move
from app.services.run_capability import decide_run_capability
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.worker_execution_profile import build_worker_execution_profile, worker_turn_refusal
from app.services.workflow_contracts.decisions import ALLOW_CHANGES, CAPABILITY_ESCALATION_DECISION

CHANGE_WORKFLOW = {"source": "db", "status": "matched", "workflow_contract": {"capability_class": "change"}}






def test_a_turn_without_a_profile_is_denied_with_an_explicit_code() -> None:
    gate = evaluate_execution_gate(None)
    assert (gate.allowed, gate.status, gate.decision_source) == (False, "denied", "missing_profile")
    move = gate_move(gate, None)
    assert (move.to_state, move.end_reason) == ("denied", "gate_missing_profile")




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






def test_the_call_agent_worker_is_gated_on_its_worker_profile() -> None:
    profile = build_worker_execution_profile("call_agent", prompt="What is the status of the release?")
    assert (profile["status"], profile["decision_source"], profile["capability"]["class"]) == (
        "allowed",
        "worker_profile",
        "read_only",
    )
    assert worker_turn_refusal("call_agent", prompt="What is the status?") is None
    assert worker_turn_refusal("call_agent", prompt="").status == "needs_clarification"


