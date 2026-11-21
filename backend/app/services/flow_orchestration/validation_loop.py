from __future__ import annotations

from typing import Any

from ...models.agent.orchestrator_agent import OrchestratorAgentRun
from ...models.runtime.flow_definition import FlowNodeRun
from ...time_utils import utc_now

VALIDATION_LOOP_SCHEMA_VERSION = "1.0"
VALIDATION_LOOP_KIND = "flow_v2_validation_loop"
DEFAULT_MAX_REPAIR_ATTEMPTS = 0


def resolve_validation_loop_config(
    *,
    definition: dict[str, Any],
    version_runtime_settings: dict[str, Any] | None = None,
    publish_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = _first_dict(
        (definition.get("validation_loop") if isinstance(definition, dict) else None),
        (version_runtime_settings or {}).get("validation_loop"),
        (publish_metadata or {}).get("validation_loop"),
    )
    enabled = bool(raw.get("enabled")) if raw else False
    require_validation = bool(raw.get("require_validation")) if raw else False
    max_repair_attempts = _clamp_int(raw.get("max_repair_attempts") if raw else None)
    repair_node_ids = [
        str(item).strip()
        for item in (raw.get("repair_node_ids") if raw else []) or []
        if str(item).strip()
    ][:20]
    fail_run_on_failure = bool(raw.get("fail_run_on_failure", True)) if raw else True
    return {
        "schema_version": VALIDATION_LOOP_SCHEMA_VERSION,
        "kind": VALIDATION_LOOP_KIND,
        "enabled": enabled or require_validation,
        "require_validation": require_validation,
        "max_repair_attempts": max_repair_attempts,
        "repair_node_ids": repair_node_ids,
        "fail_run_on_failure": fail_run_on_failure,
    }


def initialize_validation_loop(orchestrator_run: OrchestratorAgentRun, config: dict[str, Any]) -> None:
    if not config.get("enabled"):
        return
    _set_validation_loop(
        orchestrator_run,
        {
            **config,
            "status": "pending",
            "updated_at": utc_now().isoformat(),
            "checks": [],
            "failed_check_count": 0,
            "passed_check_count": 0,
            "warning_check_count": 0,
            "repair_attempts": 0,
        },
    )


def validation_loop_state(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    runtime = _runtime_policy(orchestrator_run)
    validation_loop = runtime.get("validation_loop")
    return dict(validation_loop) if isinstance(validation_loop, dict) else {}


def record_validation_outcome(
    orchestrator_run: OrchestratorAgentRun,
    *,
    node: dict[str, Any],
    node_run: FlowNodeRun,
    output: dict[str, Any],
) -> dict[str, Any] | None:
    state = validation_loop_state(orchestrator_run)
    check = _extract_validation_check(node=node, node_run=node_run, output=output)
    if not state and check is None:
        return None
    if not state:
        state = {
            **resolve_validation_loop_config(definition={"validation_loop": {"enabled": True}}),
            "status": "pending",
            "checks": [],
            "failed_check_count": 0,
            "passed_check_count": 0,
            "warning_check_count": 0,
            "repair_attempts": 0,
        }
    if check is None:
        return None

    checks = [dict(item) for item in state.get("checks") or [] if isinstance(item, dict)]
    checks.append(check)
    state["checks"] = checks[-50:]
    state["updated_at"] = utc_now().isoformat()
    state["failed_check_count"] = sum(1 for item in checks if str(item.get("status")) == "failed")
    state["passed_check_count"] = sum(1 for item in checks if str(item.get("status")) == "passed")
    state["warning_check_count"] = sum(1 for item in checks if str(item.get("status")) == "warning")
    if check["status"] == "failed":
        if _repair_allowed(state):
            state["status"] = "repair_required"
            state["required_action"] = "repair"
            state["reason"] = check.get("reason") or "Validation failed and repair policy allows repair."
        else:
            state["status"] = "failed"
            state["required_action"] = "stop"
            state["reason"] = check.get("reason") or "Validation failed and no repair policy allows retry."
    elif check["status"] == "warning" and state.get("status") not in {"failed", "repair_required"}:
        state["status"] = "warnings"
        state["required_action"] = "review_warnings"
        state["reason"] = check.get("reason") or "Validation completed with warnings."
    elif state.get("status") not in {"failed", "repair_required"}:
        state["status"] = "passed"
        state.pop("required_action", None)
        state.pop("reason", None)
    _set_validation_loop(orchestrator_run, state)
    return check


def finalize_validation_loop(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    state = validation_loop_state(orchestrator_run)
    if not state:
        return {}
    checks = [item for item in state.get("checks") or [] if isinstance(item, dict)]
    state["updated_at"] = utc_now().isoformat()
    if not checks and state.get("require_validation"):
        state["status"] = "failed"
        state["required_action"] = "stop"
        state["reason"] = "Validation was required but no validation checks were captured."
    elif not checks:
        state["status"] = "no_checks"
    elif any(str(item.get("status")) == "failed" for item in checks):
        state["status"] = "repair_required" if _repair_allowed(state) else "failed"
        state["required_action"] = "repair" if state["status"] == "repair_required" else "stop"
        state.setdefault("reason", "Validation failed.")
    elif any(str(item.get("status")) == "warning" for item in checks):
        state["status"] = "warnings"
        state["required_action"] = "review_warnings"
        state.setdefault("reason", "Validation completed with warnings.")
    else:
        state["status"] = "passed"
        state.pop("required_action", None)
        state.pop("reason", None)
    _set_validation_loop(orchestrator_run, state)
    return state


def validation_loop_blocks_completion(state: dict[str, Any]) -> bool:
    return str(state.get("status") or "") in {"failed", "repair_required"} and bool(
        state.get("fail_run_on_failure", True)
    )


def _extract_validation_check(
    *,
    node: dict[str, Any],
    node_run: FlowNodeRun,
    output: dict[str, Any],
) -> dict[str, Any] | None:
    node_type = str(node.get("type") or node_run.node_type or "").strip()
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    candidates = _validation_candidates(output)
    if not candidates and node_type != "evaluation" and not config.get("validation_check"):
        return None
    status = "passed"
    reason = ""
    for candidate in candidates:
        candidate_status, candidate_reason = _candidate_status(candidate)
        if candidate_status == "failed":
            status = "failed"
            reason = candidate_reason
            break
        if candidate_status == "warning" and status != "failed":
            status = "warning"
            reason = candidate_reason or reason
        if candidate_reason and not reason:
            reason = candidate_reason
    if node_type == "evaluation" and not candidates:
        quality_passed = output.get("quality_passed")
        if quality_passed is False:
            status = "failed"
            reason = str(output.get("reason") or "Evaluation node reported quality_passed=false.")
        else:
            status = "passed"
            reason = str(output.get("reason") or "Evaluation node completed.")
    return {
        "node_id": node_run.node_id,
        "node_run_id": node_run.id,
        "node_type": node_type,
        "status": status,
        "reason": reason,
        "captured_at": utc_now().isoformat(),
        "source": "node_output",
    }


def _validation_candidates(output: dict[str, Any]) -> list[Any]:
    candidates: list[Any] = []
    for key in ("validation", "validation_result", "quality", "test_result"):
        value = output.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    if isinstance(output.get("validations"), list):
        candidates.extend(item for item in output["validations"] if isinstance(item, dict))
    result = output.get("result")
    if isinstance(result, dict):
        for key in ("validation", "validation_result", "quality", "test_result"):
            value = result.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        if isinstance(result.get("validations"), list):
            candidates.extend(item for item in result["validations"] if isinstance(item, dict))
        contract = result.get("workspace_change_safety_contract")
        if isinstance(contract, dict) and isinstance(contract.get("validation"), dict):
            candidates.append(contract["validation"])
    return candidates


def _candidate_status(candidate: dict[str, Any]) -> tuple[str, str]:
    raw_status = str(candidate.get("status") or candidate.get("outcome") or "").strip().lower()
    passed = candidate.get("passed")
    exit_code = candidate.get("exit_code", candidate.get("validation_exit_code"))
    reason = str(candidate.get("reason") or candidate.get("message") or candidate.get("summary") or "").strip()
    if passed is False or raw_status in {"failed", "fail", "red", "error"}:
        return "failed", reason or "Validation check failed."
    if isinstance(exit_code, int) and exit_code != 0:
        return "failed", reason or f"Validation command exited with {exit_code}."
    if raw_status in {"warning", "warn", "yellow"} or candidate.get("warning") is True:
        return "warning", reason or "Validation check completed with warnings."
    return "passed", reason


def _repair_allowed(state: dict[str, Any]) -> bool:
    max_attempts = _clamp_int(state.get("max_repair_attempts"))
    attempts = _clamp_int(state.get("repair_attempts"))
    return max_attempts > attempts and bool(state.get("repair_node_ids"))


def _runtime_policy(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = policy.get("runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def _set_validation_loop(orchestrator_run: OrchestratorAgentRun, state: dict[str, Any]) -> None:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime["validation_loop"] = state
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _clamp_int(value: Any) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_MAX_REPAIR_ATTEMPTS)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_REPAIR_ATTEMPTS
    return max(0, min(parsed, 5))
