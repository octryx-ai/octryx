"""Tests for the end-of-turn stream and webhook payloads (``services/session/turn_event_payloads``)."""

from app.services.session.turn_event_payloads import (
    approval_request_payload,
    completed_webhook_payload,
    run_state_payload,
)


def test_build_chat_turn_completed_webhook_payload_preserves_completion_fields():
    payload = completed_webhook_payload(
        session_id="session-123",
        agent_type="diagnosis",
        run_status="completed",
        run_completion_reason="no_changes_needed",
        latest_assistant_message_id="message-456",
        latest_assistant_content="Completed successfully.",
    )

    assert payload == {
        "session_id": "session-123",
        "agent_type": "diagnosis",
        "run_status": "completed",
        "run_completion_reason": "no_changes_needed",
        "latest_assistant_message_id": "message-456",
        "latest_assistant_content": "Completed successfully.",
    }


def test_build_chat_turn_run_state_payload_keeps_optional_fields_out_by_default():
    payload = run_state_payload(
        run_status="completed",
        run_completion_reason="no_changes_needed",
    )

    assert payload == {
        "runStatus": "completed",
        "runCompletionReason": "no_changes_needed",
    }


def test_build_chat_turn_run_state_payload_includes_recovery_and_error_flags():
    payload = run_state_payload(
        run_status="failed",
        run_completion_reason="error",
        recovered_from_late_exception=True,
        error="boom",
    )

    assert payload == {
        "runStatus": "failed",
        "runCompletionReason": "error",
        "recoveredFromLateException": True,
        "error": "boom",
    }


def test_build_chat_turn_approval_request_payload_matches_pending_response_contract():
    assert approval_request_payload() == {
        "runStatus": "awaiting_approval",
        "runCompletionReason": "approval_required",
    }
