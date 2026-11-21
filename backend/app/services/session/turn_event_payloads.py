"""Stream and webhook payloads a chat turn emits when it ends.

The camelCase stream payloads are the contract of the chat UI's session stream; the
``session.completed`` webhook payload is the outbound webhook contract. Both stay
byte-identical for every entry path that finishes a turn.
"""

from __future__ import annotations

from typing import Any

from .run_state import RUN_STATUS_AWAITING_APPROVAL


def approval_request_payload() -> dict[str, str]:
    return {
        "runStatus": RUN_STATUS_AWAITING_APPROVAL,
        "runCompletionReason": "approval_required",
    }


def completed_webhook_payload(
    *,
    session_id: str,
    agent_type: str | None,
    run_status: str,
    run_completion_reason: str,
    latest_assistant_message_id: str | None,
    latest_assistant_content: str | None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_type": agent_type,
        "run_status": run_status,
        "run_completion_reason": run_completion_reason,
        "latest_assistant_message_id": latest_assistant_message_id,
        "latest_assistant_content": latest_assistant_content,
    }


def run_state_payload(
    *,
    run_status: str,
    run_completion_reason: str,
    recovered_from_late_exception: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runStatus": run_status,
        "runCompletionReason": run_completion_reason,
    }
    if recovered_from_late_exception:
        payload["recoveredFromLateException"] = True
    if error is not None:
        payload["error"] = error
    return payload


__all__ = ["approval_request_payload", "completed_webhook_payload", "run_state_payload"]
