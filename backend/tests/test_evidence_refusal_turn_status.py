"""The answer-evidence guard's final refusal is a recorded runtime stop on the real persistence path."""

from __future__ import annotations

from app.services.answer_evidence.check import (
    REFUSAL_REASON_UNCITED,
)
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_KEY,
    RUNTIME_STOP_REASON_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary import runtime_outcome_from_trace

SOURCE = "https://example.org/owner.java"
HISTORY = [{"tool_name": "web_fetch", "result": {"source_url": SOURCE, "content": "Owner holds a list of pets."}}]
UNCITED = "Owner holds a list of pets."
INVENTED = "Owner holds a list of pets ([Owner](https://example.org/invented.java))."
USAGE = {"prompt_tokens": 120, "completion_tokens": 40}




def _snapshot(user_message_id: str | None = None) -> dict:
    profile = {
        "version": "execution_profile.v1", "status": "allowed", "profile_id": "direct_chat_safe",
        "decision_source": "direct_chat_safe", "execution_strategy": "direct",
    }
    return build_turn_execution_snapshot(
        execution_profile=profile,
        gate=evaluate_execution_gate(profile),
        session_metadata={"current_turn_user_message_id": user_message_id} if user_message_id else {},
        agent_definition=None,
    )
















def test_unknown_or_forged_answer_evidence_stops_still_read_unknown():
    for reason in ("answer_evidence_other", "answer_evidence_uncited ", None):
        forged = {TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: "stopped", RUNTIME_STOP_REASON_KEY: reason}}
        assert runtime_outcome_from_trace(forged, {}) == "unknown"
    refused_without_marker = {TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()}
    assert runtime_outcome_from_trace(refused_without_marker, {"refusal_reason": REFUSAL_REASON_UNCITED}) == "unknown", (
        "a refusal reason in the raw output is never read as a stop on its own"
    )
