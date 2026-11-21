from __future__ import annotations

from datetime import datetime
from typing import Any

from ...models.agent.orchestrator_agent import OrchestratorAgentRun
from ...models.runtime.flow_definition import FlowNodeRun
from ...time_utils import utc_now

PLAN_SCHEMA_VERSION = "1.0"
PLAN_KIND = "flow_v2_plan"
TERMINAL_STEP_STATUSES = {"done", "skipped", "failed", "cancelled"}


def initialize_flow_run_plan(
    orchestrator_run: OrchestratorAgentRun,
    *,
    nodes: list[dict[str, Any]],
    ordered_node_ids: list[str],
) -> None:
    node_map = {str(node.get("id") or ""): node for node in nodes}
    steps = []
    for position, node_id in enumerate(ordered_node_ids):
        node = node_map.get(node_id, {})
        steps.append(
            {
                "id": node_id,
                "node_id": node_id,
                "label": str(node.get("label") or node_id),
                "type": str(node.get("type") or ""),
                "status": "pending",
                "position": position,
                "links": {"flow_node_id": node_id},
            }
        )
    _set_runtime_plan(
        orchestrator_run,
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "kind": PLAN_KIND,
            "status": "pending",
            "updated_at": utc_now().isoformat(),
            "steps": steps,
        },
    )


def ensure_flow_run_plan(
    orchestrator_run: OrchestratorAgentRun,
    *,
    nodes: list[dict[str, Any]],
    ordered_node_ids: list[str],
) -> None:
    if flow_run_plan_state(orchestrator_run).get("kind") == PLAN_KIND:
        return
    initialize_flow_run_plan(orchestrator_run, nodes=nodes, ordered_node_ids=ordered_node_ids)


def flow_run_plan_state(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    runtime = _runtime_policy(orchestrator_run)
    plan = runtime.get("plan")
    return dict(plan) if isinstance(plan, dict) else {}


def sync_flow_run_plan_from_node_runs(
    orchestrator_run: OrchestratorAgentRun,
    node_runs: list[FlowNodeRun],
) -> None:
    for node_run in sorted(node_runs, key=lambda item: item.created_at or datetime.min):
        update_flow_plan_step(
            orchestrator_run,
            node_id=node_run.node_id,
            status=_plan_status_from_node_status(node_run.status),
            node_run_id=node_run.id,
            reason=node_run.error or _reason_from_node_run(node_run),
        )


def update_flow_plan_step(
    orchestrator_run: OrchestratorAgentRun,
    *,
    node_id: str,
    status: str,
    node_run_id: str | None = None,
    reason: str | None = None,
    required_action: str | None = None,
) -> None:
    if not node_id:
        _update_plan_status(orchestrator_run, status=status)
        return
    plan = flow_run_plan_state(orchestrator_run)
    if not plan:
        return
    current = utc_now().isoformat()
    steps = []
    for raw_step in plan.get("steps") or []:
        if not isinstance(raw_step, dict):
            continue
        step = dict(raw_step)
        if step.get("node_id") == node_id or step.get("id") == node_id:
            step["status"] = status
            step["updated_at"] = current
            links = dict(step.get("links") or {})
            links["flow_node_id"] = node_id
            if node_run_id:
                links["flow_node_run_id"] = node_run_id
            step["links"] = links
            if reason:
                step["reason"] = reason
            else:
                step.pop("reason", None)
            if required_action:
                step["required_action"] = required_action
            else:
                step.pop("required_action", None)
        steps.append(step)
    plan["steps"] = steps
    plan["updated_at"] = current
    plan["status"] = _derive_plan_status(steps)
    _set_runtime_plan(orchestrator_run, plan)


def _update_plan_status(orchestrator_run: OrchestratorAgentRun, *, status: str) -> None:
    plan = flow_run_plan_state(orchestrator_run)
    if not plan:
        return
    steps = [dict(step) for step in plan.get("steps") or [] if isinstance(step, dict)]
    plan["status"] = "completed" if status == "completed" and _all_steps_terminal(steps) else _derive_plan_status(steps)
    plan["updated_at"] = utc_now().isoformat()
    _set_runtime_plan(orchestrator_run, plan)


def _derive_plan_status(steps: list[dict[str, Any]]) -> str:
    statuses = {str(step.get("status") or "") for step in steps}
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses:
        return "blocked"
    if "running" in statuses:
        return "in_progress"
    if statuses and statuses <= TERMINAL_STEP_STATUSES:
        return "completed"
    return "pending"


def _all_steps_terminal(steps: list[dict[str, Any]]) -> bool:
    return bool(steps) and all(str(step.get("status") or "") in TERMINAL_STEP_STATUSES for step in steps)


def _plan_status_from_node_status(status: str) -> str:
    if status == "completed":
        return "done"
    if status == "paused":
        return "blocked"
    if status in {"running", "skipped", "failed", "cancelled"}:
        return status
    return "pending"


def _reason_from_node_run(node_run: FlowNodeRun) -> str | None:
    output = node_run.output_json if isinstance(node_run.output_json, dict) else {}
    trace_refs = node_run.trace_refs_json if isinstance(node_run.trace_refs_json, dict) else {}
    reason = output.get("reason") or trace_refs.get("reason") or trace_refs.get("recovery_reason")
    return str(reason) if reason else None


def _runtime_policy(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = policy.get("runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def _set_runtime_plan(orchestrator_run: OrchestratorAgentRun, plan: dict[str, Any]) -> None:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime["plan"] = plan
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy
