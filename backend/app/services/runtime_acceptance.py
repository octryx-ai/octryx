from __future__ import annotations

from typing import Any

from ..models.agent.orchestrator_agent import OrchestratorAgentRun
from ..time_utils import utc_now
from .flow_orchestration.validation_loop import validation_loop_state
from .runtime_failure_taxonomy import runtime_failure_state

ACCEPTANCE_SCHEMA_VERSION = "1.0"
ACCEPTANCE_KIND = "runtime_acceptance_state"


def derive_runtime_acceptance_state(
    orchestrator_run: OrchestratorAgentRun,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    run_status = str(orchestrator_run.status or "").strip() or "unknown"
    validation = validation_loop_state(orchestrator_run)
    failure = runtime_failure_state(orchestrator_run)
    validation_status = str(validation.get("status") or "").strip()
    state = "pending"
    required_action = "continue"
    accepted = False
    review_required = False

    if run_status == "completed":
        accepted = True
        required_action = "none"
        if validation_status == "passed":
            state = "validated"
        elif validation_status == "warnings" or _warning_count(validation) > 0:
            state = "warnings"
            required_action = "review_warnings"
        else:
            state = "completed"
    elif run_status == "paused":
        state = "needs_review"
        required_action = "human_review"
        review_required = True
    elif run_status == "cancelled":
        state = "rejected"
        required_action = "review_rejection"
        review_required = True
    elif run_status == "failed":
        state = "failed"
        required_action = str(failure.get("required_action") or validation.get("required_action") or "inspect_trace")
        review_required = True
    elif run_status == "running":
        state = "running"
    else:
        state = run_status or "unknown"
        required_action = "inspect_trace"

    return {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "kind": ACCEPTANCE_KIND,
        "state": state,
        "technical_status": run_status,
        "accepted": accepted,
        "review_required": review_required,
        "required_action": required_action,
        "reason": reason or _reason_for_state(state, validation=validation, failure=failure),
        "validation_status": validation_status or None,
        "warning_count": _warning_count(validation),
        "failure_category": failure.get("category"),
        "updated_at": utc_now().isoformat(),
    }


def record_runtime_acceptance(orchestrator_run: OrchestratorAgentRun, acceptance: dict[str, Any]) -> None:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime["acceptance"] = acceptance
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy


def runtime_acceptance_state(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = policy.get("runtime")
    acceptance = runtime.get("acceptance") if isinstance(runtime, dict) else None
    return dict(acceptance) if isinstance(acceptance, dict) else {}


def _warning_count(validation: dict[str, Any]) -> int:
    count = validation.get("warning_check_count")
    if isinstance(count, int):
        return max(0, count)
    return sum(
        1
        for item in validation.get("checks") or []
        if isinstance(item, dict) and item.get("status") == "warning"
    )


def _reason_for_state(state: str, *, validation: dict[str, Any], failure: dict[str, Any]) -> str:
    if state == "validated":
        return "Run completed and validation checks passed."
    if state == "warnings":
        return "Run completed with non-blocking validation warnings."
    if state == "completed":
        return "Run completed without explicit acceptance validation."
    if state == "needs_review":
        return "Run is waiting for human review."
    if state == "rejected":
        return "Run was rejected or cancelled by review action."
    if state == "failed":
        return str(failure.get("summary") or validation.get("reason") or "Run failed before acceptance.")
    return "Run acceptance is not terminal yet."


__all__ = [
    "derive_runtime_acceptance_state",
    "record_runtime_acceptance",
    "runtime_acceptance_state",
]
