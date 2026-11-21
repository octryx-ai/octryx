"""Contract tests for the execution gate at the runtime boundary."""

from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)
from app.services.session.execution_gate import (
    GATE_SOURCE_MISSING_PROFILE,
    GATE_SOURCE_PROFILE,
    GATE_SOURCE_UNKNOWN_STATUS,
    evaluate_execution_gate,
)


def _profile(status: str, reason: str = "") -> dict:
    return {"status": status, "reason": reason}


def test_allowed_profile_executes() -> None:
    decision = evaluate_execution_gate(_profile(EXECUTION_PROFILE_STATUS_ALLOWED, "Policy matched."))
    assert decision.allowed is True
    assert decision.decision_source == GATE_SOURCE_PROFILE
    assert decision.user_message == ""


def test_missing_profile_blocks_by_default() -> None:
    decision = evaluate_execution_gate(None)
    assert decision.allowed is False
    assert decision.decision_source == GATE_SOURCE_MISSING_PROFILE
    assert "no execution profile" in decision.user_message.lower()


def test_denied_profile_blocks() -> None:
    decision = evaluate_execution_gate(_profile(EXECUTION_PROFILE_STATUS_DENIED, "Tool policy denied coding."))
    assert decision.allowed is False
    assert decision.status == EXECUTION_PROFILE_STATUS_DENIED
    assert "denied by execution policy" in decision.user_message
    assert "Tool policy denied coding." in decision.user_message


def test_needs_approval_profile_blocks_with_approval_instruction() -> None:
    decision = evaluate_execution_gate(_profile(EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL))
    assert decision.allowed is False
    assert "requires an approval" in decision.user_message


def test_needs_configuration_profile_blocks_with_configuration_instruction() -> None:
    decision = evaluate_execution_gate(
        _profile(EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION, "No runtime target is configured.")
    )
    assert decision.allowed is False
    assert "requires configuration" in decision.user_message
    assert "No runtime target is configured." in decision.user_message


def test_needs_clarification_profile_blocks_with_clarification_instruction() -> None:
    decision = evaluate_execution_gate(
        _profile(EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION, "Prompt is empty.")
    )
    assert decision.allowed is False
    assert "needs clarification" in decision.user_message
    assert "Prompt is empty." in decision.user_message


def test_unknown_status_blocks_by_default() -> None:
    decision = evaluate_execution_gate(_profile("totally_new_state"))
    assert decision.allowed is False
    assert decision.decision_source == GATE_SOURCE_UNKNOWN_STATUS
    assert "was not executed" in decision.user_message


def test_profile_without_status_blocks_by_default() -> None:
    decision = evaluate_execution_gate({"reason": "corrupted metadata"})
    assert decision.allowed is False
    assert decision.decision_source == GATE_SOURCE_UNKNOWN_STATUS
    assert decision.status == "missing"


def test_non_dict_profile_blocks_by_default() -> None:
    decision = evaluate_execution_gate("allowed")
    assert decision.allowed is False
    assert decision.decision_source == GATE_SOURCE_UNKNOWN_STATUS


def test_gate_metadata_shape_is_stable() -> None:
    decision = evaluate_execution_gate(_profile(EXECUTION_PROFILE_STATUS_DENIED, "why"))
    assert decision.to_metadata() == {
        "allowed": False,
        "status": EXECUTION_PROFILE_STATUS_DENIED,
        "decision_source": GATE_SOURCE_PROFILE,
        "reason": "why",
    }
