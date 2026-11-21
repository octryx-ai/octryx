"""The registry of code-defined workflow families and the contract a turn's selection builds.

Two families exist: ``coding_change_tdd`` (secure-work coding execution, coding phases of a
workflow run) and ``knowledge_request`` (the triage phase of ``jira-intake-triage``). The family
comes only from the turn's selection (``workflow_routing.workflow_selection``); the prompt never
picks one.
"""

from __future__ import annotations

from typing import Any

from ..workflow_runs.phase_marker import is_run_phase_contract
from .coding_change import coding_change_tdd_definition
from .knowledge_request import knowledge_request_definition
from .models import WorkflowDefinition


def workflow_definitions() -> tuple[WorkflowDefinition, ...]:
    return (coding_change_tdd_definition(), knowledge_request_definition())


def get_workflow_definition(workflow_id: str) -> WorkflowDefinition | None:
    """Return the registry definition for an explicit workflow id, if any."""
    normalized_id = str(workflow_id or "").strip()
    if not normalized_id:
        return None
    return next((item for item in workflow_definitions() if item.workflow_id == normalized_id), None)


def workflow_phase_tool_names(workflow_contract: dict[str, Any] | None) -> list[str]:
    """The preferred tools of the contract's family phases, in order (none for a run phase)."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    if is_run_phase_contract(contract):
        # A phase reuses a family id for its message only: the family never plans its tools.
        return []
    definition = get_workflow_definition(str(contract.get("workflow_id") or ""))
    if definition is None:
        return []
    names: list[str] = []
    for phase in definition.phases:
        for tool_name in phase.preferred_tools:
            normalized = str(tool_name or "").strip()
            if normalized and normalized not in names:
                names.append(normalized)
    return names


def build_task_workflow_contract(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None,
    route_reason: str = "",
    project_id: str | None = None,
    capability_type: str | None = None,
) -> dict[str, Any]:
    """Build the contract of the workflow the turn's routing resolution selected, or ``{}``.

    The family comes only from the selection: the routing resolution in ``request_analysis``,
    or, without one, the explicit ``workflow_contract`` a caller put there. No selection means
    no contract. The definition's ``matcher`` is an applicability guard on the selected family;
    it reads only the configured contract, never the prompt.
    """
    from ..workflow_routing.workflow_selection import workflow_selection_from_analysis

    selection = workflow_selection_from_analysis(request_analysis)
    if not selection.selected:
        return {}
    definition = get_workflow_definition(selection.workflow_id)
    if definition is None:
        return {}
    arguments = {
        "request_analysis": request_analysis,
        "route_reason": route_reason,
        "project_id": project_id,
        "capability_type": capability_type,
    }
    if not definition.matcher(user_message, **arguments):
        return {}
    contract = definition.contract_builder(user_message, **arguments)
    if not isinstance(contract, dict) or not contract:
        return {}
    enriched = dict(contract)
    enriched.setdefault("workflow_id", definition.workflow_id)
    enriched.setdefault("workflow_version", 1)
    enriched.setdefault("intent_type", definition.intent_type)
    enriched.setdefault("source_user_message", str(user_message or ""))
    enriched["phases"] = [phase.to_dict() for phase in definition.phases]
    # The evidence a selected definition declares as required travels with the contract,
    # whatever the family builder copies, so the requirement check sees it.
    configured = (request_analysis or {}).get("workflow_contract")
    required = configured.get("required_evidence_tools") if isinstance(configured, dict) else None
    if isinstance(required, list) and required:
        enriched["required_evidence_tools"] = [str(tool).strip() for tool in required if str(tool or "").strip()]
    return enriched


def plan_next_workflow_tool_calls(
    workflow_contract: dict[str, Any] | None,
    *,
    turn_tool_history: list[dict[str, Any]],
    covered_evidence_axes: set[str] | None,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return []
    if is_run_phase_contract(workflow_contract):
        # A phase reuses a family id for its message only: the family definition never forces its calls.
        return []
    definition = get_workflow_definition(str(workflow_contract.get("workflow_id") or ""))
    if definition is None:
        return []
    return definition.planner(
        dict(workflow_contract),
        turn_tool_history=[item for item in turn_tool_history if isinstance(item, dict)],
        covered_evidence_axes=covered_evidence_axes,
        allowed_tool_names=allowed_tool_names,
    )


def workflow_contract_from_request_analysis(request_analysis: dict[str, Any] | None) -> dict[str, Any]:
    """The turn's workflow contract from its request analysis, ``{}`` without one."""
    if not isinstance(request_analysis, dict):
        return {}
    workflow_contract = request_analysis.get("workflow_contract")
    if not isinstance(workflow_contract, dict) or not str(workflow_contract.get("workflow_id") or "").strip():
        return {}
    return dict(workflow_contract)


__all__ = [
    "build_task_workflow_contract",
    "get_workflow_definition",
    "plan_next_workflow_tool_calls",
    "workflow_contract_from_request_analysis",
    "workflow_definitions",
    "workflow_phase_tool_names",
]
