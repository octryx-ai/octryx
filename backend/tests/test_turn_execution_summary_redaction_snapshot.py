"""The redaction contract and snapshot projection, stamping, carrying and revalidation."""

import json
from types import SimpleNamespace

from app.agent.core.runtime.turn_execution_binding import (
    bind_turn_execution_snapshot,
    carry_turn_execution_snapshot,
    clear_turn_execution_snapshot,
    mark_turn_runtime_finished,
    stamp_turn_execution_snapshot,
)
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
    read_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary import TurnApprovalEvidence, TurnToolCallEvidence
from tests.turn_execution_summary_support import PROMPT, SECRET, _profile, _snapshot, _summary

_FORBIDDEN_KEYS = {
    "reason",
    "routing_reason",
    "workflow_contract",
    "policy",
    "runtime",
    "llm_router",
    "system_prompt",
    "input_messages",
    "inputMessages",
    "context_snapshot",
    "contextSnapshot",
    "tool_trace",
    "result",
    "parameters",
    "arguments",
    "raw_output",
    "error",
    "tool_policy",
}


_ALLOWED_TOP_LEVEL = {
    "version",
    "trace_id",
    "session_id",
    "message_id",
    "run_identity",
    "state",
    "state_reason",
    "next_action",
    "execution_profile",
    "agent",
    "model",
    "capabilities_used",
    "approvals",
    "artifacts",
    "usage",
    "decision_request",
    "workflow_proposal",
    # The answer evidence guard's closed record (E1); null when the trace has none.
    "answer_evidence",
    # The selected workflow's check record (A6); null when the turn ran no workflow with checks.
    "workflow_checks",
    # The checked reply format's closed result; null for free text or an unchecked reply.
    "reply_contract",
    # Closed content policy notices of the turn; empty when no content policy acted.
    "content_obligations",
}


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value)) if value else set()
    return set()


def test_redaction_contract_excludes_forbidden_fields_and_values() -> None:
    hostile_agent = {"id": f"agent {SECRET}", "name": f"Name\n{PROMPT}=x"}
    snapshot = _snapshot(
        _profile(profile_id=f"id with spaces {SECRET}", execution_strategy="Bearer abc def"),
        agent=hostile_agent,
    )
    summary = _summary(
        snapshot,
        provider=f"Authorization: Bearer {SECRET}",
        approvals=(TurnApprovalEvidence(f"x {SECRET}", "tool", "pending"),),
        tool_calls=(TurnToolCallEvidence(f"token={SECRET}", "success"),),
    )
    payload = json.dumps(summary)
    assert SECRET not in payload
    assert "hunter2" not in payload
    assert set(summary) == _ALLOWED_TOP_LEVEL
    assert not (_all_keys(summary) & _FORBIDDEN_KEYS)
    assert summary["execution_profile"]["profile_id"] is None
    assert summary["execution_profile"]["execution_strategy"] is None
    # Hostile agent values drop to None; the closed selection source survives.
    assert summary["agent"] == {"id": None, "name": None, "selection_source": "explicit"}
    assert summary["model"]["provider"] is None


def test_snapshot_projection_drops_free_text_and_policies() -> None:
    snapshot = _snapshot()
    payload = json.dumps(snapshot)
    assert SECRET not in payload
    assert "hunter2" not in payload
    assert set(snapshot["execution_profile"]) == {
        "capability",
        "present",
        "version",
        "status",
        "profile_id",
        "decision_source",
        "execution_strategy",
        "effective_agent_type",
        "workflow_id",
        "workflow_key",
    }
    assert snapshot["gate"] == {"allowed": True, "status": "allowed", "decision_source": "execution_profile"}


def test_snapshot_workflow_key_requires_matching_resolution() -> None:
    snapshot = build_turn_execution_snapshot(
        execution_profile=_profile(),
        gate=evaluate_execution_gate(_profile()),
        session_metadata={
            "workflow_routing_policy_resolution": {"workflow_id": "other", "workflow_key": "other-key"}
        },
        agent_definition=None,
    )
    assert snapshot["execution_profile"]["workflow_key"] is None


def test_read_snapshot_revalidates_stored_values() -> None:
    snapshot = _snapshot()
    snapshot["execution_profile"]["profile_id"] = f"forged {SECRET}"
    snapshot["gate"]["status"] = "super_allowed"
    status, read = read_turn_execution_snapshot({TURN_EXECUTION_SNAPSHOT_KEY: snapshot})
    assert status == "ok"
    assert read["execution_profile"]["profile_id"] is None
    assert read["gate"]["status"] == "unknown"


def test_stamp_uses_only_bound_snapshot_and_drops_forged_values() -> None:
    forged = {TURN_EXECUTION_SNAPSHOT_KEY: {"version": "turn_execution_snapshot.v1"}, "x": 1}
    assert stamp_turn_execution_snapshot("unbound-session", forged) == {"x": 1}

    bind_turn_execution_snapshot("bound-session", _snapshot())
    bind_turn_execution_snapshot("child-session", _snapshot(_profile("denied")))
    stamped = stamp_turn_execution_snapshot("bound-session", forged)
    assert stamped[TURN_EXECUTION_SNAPSHOT_KEY]["gate"]["allowed"] is True
    child = stamp_turn_execution_snapshot("child-session", {})
    assert child[TURN_EXECUTION_SNAPSHOT_KEY]["gate"]["allowed"] is False


def test_carry_preserves_persisted_snapshot_on_context_refresh() -> None:
    previous = {TURN_EXECUTION_SNAPSHOT_KEY: {"version": "turn_execution_snapshot.v1"}, "old": True}
    refreshed = carry_turn_execution_snapshot(previous, {"new": True, TURN_EXECUTION_SNAPSHOT_KEY: "forged"})
    assert refreshed == {"new": True, TURN_EXECUTION_SNAPSHOT_KEY: {"version": "turn_execution_snapshot.v1"}}
    assert carry_turn_execution_snapshot({}, {"new": True}) == {"new": True}


def test_snapshot_records_the_turn_user_message_token_only_when_safe() -> None:
    def build(metadata):
        return build_turn_execution_snapshot(
            execution_profile=_profile(),
            gate=evaluate_execution_gate(_profile()),
            session_metadata=metadata,
            agent_definition=None,
        )

    assert build({"current_turn_user_message_id": "msg-1"})["turn"] == {"user_message_id": "msg-1", "sequence": None}
    assert build({"current_turn_user_message_id": f"x {SECRET}"})["turn"]["user_message_id"] is None
    assert build({})["turn"]["user_message_id"] is None


def test_read_snapshot_revalidates_turn_and_runtime_outcome() -> None:
    snapshot = {
        **_snapshot(),
        "turn": {"user_message_id": f"bad {SECRET}", "sequence": True},
        RUNTIME_OUTCOME_KEY: "completed",
    }
    _status, read = read_turn_execution_snapshot({TURN_EXECUTION_SNAPSHOT_KEY: snapshot})
    assert read["turn"] == {"user_message_id": None, "sequence": None}
    assert read[RUNTIME_OUTCOME_KEY] is None
    _status, without_turn = read_turn_execution_snapshot({TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), "turn": None}})
    assert without_turn["turn"] == {"user_message_id": None, "sequence": None}


def test_stamp_assigns_turn_sequence_and_drops_forged_outcome() -> None:
    session_id = "sequence-session"
    bind_turn_execution_snapshot(session_id, _snapshot())
    try:
        forged = {TURN_EXECUTION_SNAPSHOT_KEY: {**_snapshot(), RUNTIME_OUTCOME_KEY: RUNTIME_OUTCOME_FINISHED}}
        first = stamp_turn_execution_snapshot(session_id, forged)[TURN_EXECUTION_SNAPSHOT_KEY]
        second = stamp_turn_execution_snapshot(session_id, {})[TURN_EXECUTION_SNAPSHOT_KEY]
        assert first["turn"]["sequence"] == 0
        assert second["turn"]["sequence"] == 1
        assert RUNTIME_OUTCOME_KEY not in first
    finally:
        clear_turn_execution_snapshot(session_id)


def test_mark_finished_only_touches_stamped_traces_and_survives_context_refresh() -> None:
    trace = SimpleNamespace(context_snapshot_json={TURN_EXECUTION_SNAPSHOT_KEY: _snapshot(), "x": 1})
    original = trace.context_snapshot_json
    mark_turn_runtime_finished(trace)
    assert trace.context_snapshot_json is not original
    assert trace.context_snapshot_json[TURN_EXECUTION_SNAPSHOT_KEY][RUNTIME_OUTCOME_KEY] == RUNTIME_OUTCOME_FINISHED
    assert RUNTIME_OUTCOME_KEY not in original[TURN_EXECUTION_SNAPSHOT_KEY]
    refreshed = carry_turn_execution_snapshot(trace.context_snapshot_json, {"y": 2})
    assert refreshed[TURN_EXECUTION_SNAPSHOT_KEY][RUNTIME_OUTCOME_KEY] == RUNTIME_OUTCOME_FINISHED

    unstamped = SimpleNamespace(context_snapshot_json={"x": 1})
    mark_turn_runtime_finished(unstamped)
    assert unstamped.context_snapshot_json == {"x": 1}
    mark_turn_runtime_finished({"not": "a trace"})
