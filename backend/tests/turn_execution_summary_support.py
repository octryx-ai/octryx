"""Profiles, snapshots, evidence and summary builders shared by the turn execution summary contract tests."""

from types import SimpleNamespace

from app.agent.runtime.turn_execution_binding import mark_turn_runtime_stopped
from app.services.session.execution_gate import evaluate_execution_gate
from app.services.session.turn_execution_snapshot import (
    TURN_EXECUTION_SNAPSHOT_KEY,
    build_turn_execution_snapshot,
)
from app.services.session.turn_execution_summary import (
    TurnExecutionEvidence,
    build_turn_execution_summary,
    runtime_outcome_from_trace,
)

RUN_ID, ATTEMPT_ID = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


SECRET = "sk-live-SECRET-token-123"


PROMPT = "Please deploy prod with password hunter2"


def _profile(status: str = "allowed", **overrides) -> dict:
    profile = {
        "version": "execution_profile.v1",
        "status": status,
        "profile_id": "workflow:aws_evidence" if status == "allowed" else f"{status}:explicit_workflow_key",
        "decision_source": "explicit_workflow_key",
        "reason": f"Reason echoing the prompt: {PROMPT}",
        "routing_reason": f"routing {SECRET}",
        "execution_strategy": "workflow",
        "effective_agent_type": "diagnosis",
        "workflow_id": "aws_evidence",
        "workflow_contract": {"phases": [{"preferred_tools": ["run_shell"], "goal": PROMPT}]},
        "policy": {"policy_id": "p-1", "tool_policy": {"token": SECRET}},
        "runtime": {"runtime_label": SECRET},
        "llm_router": {"reasoning": PROMPT},
    }
    profile.update(overrides)
    return profile


def _snapshot(profile=None, *, gate_profile=None, agent=None) -> dict:
    profile = _profile() if profile is None else profile
    gate = evaluate_execution_gate(profile if gate_profile is None else gate_profile)
    return build_turn_execution_snapshot(
        execution_profile=profile,
        gate=gate,
        session_metadata={
            "workflow_routing_policy_resolution": {
                "workflow_id": "aws_evidence",
                "workflow_key": "aws-evidence",
                "tool_policy": {"token": SECRET},
            },
            "execution_profile": {"status": "denied"},
            "agent_selection_source": "explicit",
            # W22b: the turn's tool surface, as ``plan_and_record_turn_tool_surface`` records it.
            "tool_surface_source": "governed_default",
            "tool_surface_set": "diagnosis.v2",
        },
        agent_definition=agent or {"id": "agent-1", "name": "Cloud Reviewer", "system_prompt": PROMPT},
    )


def _evidence(snapshot=None, **overrides) -> TurnExecutionEvidence:
    context = {"system_prompt": PROMPT, "recent_history": [{"content": SECRET}]}
    if snapshot is not None:
        context[TURN_EXECUTION_SNAPSHOT_KEY] = snapshot
    values = {
        "trace_id": "trace-1",
        "session_id": "session-1",
        "message_id": "message-1",
        "provider": "openrouter",
        "model": "stepfun/step-3.5-flash:free",
        "context_snapshot": context,
        "runtime_outcome": "finished",
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }
    values.update(overrides)
    return TurnExecutionEvidence(**values)


def _summary(snapshot=None, **overrides) -> dict:
    return build_turn_execution_summary(_evidence(snapshot, **overrides))


def _stopped_summary(reason) -> dict:
    trace = SimpleNamespace(context_snapshot_json={TURN_EXECUTION_SNAPSHOT_KEY: _snapshot()})
    mark_turn_runtime_stopped(trace, reason)
    context = trace.context_snapshot_json
    return _summary(None, context_snapshot=context, runtime_outcome=runtime_outcome_from_trace(context, {}))
