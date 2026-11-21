"""Whether a turn's workflow contract is satisfied, so the loop may give the final answer."""

from __future__ import annotations

from typing import Any

from ..workflow_runs.phase_marker import is_run_phase_contract
from .registry import plan_next_workflow_tool_calls

_WORKSPACE_MUTATION_TOOLS = frozenset(
    {"write_workspace_file", "edit_workspace_file", "multi_edit_workspace_file", "apply_patch_workspace"}
)


def _code_change_satisfied(turn_tool_history: list[dict[str, Any]]) -> bool:
    has_workspace_mutation = False
    latest_green_test = False
    for item in turn_tool_history:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        if tool_name in _WORKSPACE_MUTATION_TOOLS:
            has_workspace_mutation = True
        if tool_name == "run_test_suite" and isinstance(result, dict) and result.get("all_green") is True:
            latest_green_test = True
    return has_workspace_mutation and latest_green_test


def workflow_artifact_contract_satisfied(
    workflow_contract: dict[str, Any] | None,
    *,
    turn_tool_history: list[dict[str, Any]],
) -> bool:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return True
    if not str(workflow_contract.get("workflow_id") or "").strip():
        return False
    if is_run_phase_contract(workflow_contract):
        # A phase turn has no family artifact contract: the run's phase checks (turn end) decide it is done,
        # so it is never "ready for the final answer" mid-turn and keeps its tools.
        return False
    if str(workflow_contract.get("artifact_type") or "").strip() == "code":
        return _code_change_satisfied(turn_tool_history)
    # A family without an artifact is done when its planner has nothing left to plan.
    return not plan_next_workflow_tool_calls(
        workflow_contract,
        turn_tool_history=turn_tool_history,
        covered_evidence_axes=set(),
        allowed_tool_names=None,
    )


__all__ = ["workflow_artifact_contract_satisfied"]
