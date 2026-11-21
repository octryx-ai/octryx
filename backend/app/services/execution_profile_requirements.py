"""Deterministic workflow tool requirement checks feeding the execution profile.

A matched workflow contract plans its work through the ``preferred_tools`` of its
phases. When every planned tool is unavailable for the current project — because
the owning connectors are not active or the project tool policy denies them — the
workflow cannot execute anything it planned. Running it anyway produces the exact
hidden-failure behavior the platform forbids.

This module turns that situation into an explicit execution profile state before
the run starts:

- all planned tools blocked, at least one by an inactive connector →
  ``needs_configuration`` (activating the connector is the actionable fix)
- all planned tools denied purely by project tool policy → ``denied``
- at least one planned tool available → the requirement is satisfied and the
  profile stays as produced

A definition may also declare ``required_evidence_tools``: the evidence its
answer cannot exist without, e.g. ``aws_topology_snapshot`` for an AWS topology
diagram. Every declared tool must be available, not just one planned tool; an
optional connector a definition merely allows never blocks a turn. A required tool
behind an inactive connector → ``needs_configuration`` with reason code
``connector_not_active_for_project``, before the loop runs any tool.

The runtime execution gate (``services/session/execution_gate.py``) enforces the
resulting status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.visibility import tool_visibility_decision
from .execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)
from .tool_access_policy import tool_project_policy_decision

REQUIREMENT_DECISION_SOURCE = "workflow_tool_requirements"
REQUIRED_EVIDENCE_TOOLS_KEY = "required_evidence_tools"
REASON_CODE_CONNECTOR_INACTIVE = "connector_not_active_for_project"
REASON_CODE_TOOL_POLICY_DENIED = "tool_denied_by_project_policy"


@dataclass(frozen=True, slots=True)
class WorkflowToolRequirementDecision:
    """Outcome of checking a workflow contract's planned tools against the project."""

    satisfied: bool
    status: str
    reason: str
    workflow_id: str
    available_tools: tuple[str, ...]
    inactive_connectors: tuple[str, ...]
    inactive_connector_tools: tuple[str, ...]
    policy_denied_tools: tuple[str, ...]
    reason_code: str = ""
    required_tools: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "status": self.status,
            "reason": self.reason,
            "reason_code": self.reason_code or None,
            "required_tools": list(self.required_tools),
            "workflow_id": self.workflow_id or None,
            "available_tools": list(self.available_tools),
            "inactive_connectors": list(self.inactive_connectors),
            "inactive_connector_tools": list(self.inactive_connector_tools),
            "policy_denied_tools": list(self.policy_denied_tools),
        }


def preferred_workflow_tools(workflow_contract: dict[str, Any] | None) -> tuple[str, ...]:
    """Return the unique planned tool names across all phases of a contract."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    phases = contract.get("phases")
    if not isinstance(phases, list):
        return ()
    seen: dict[str, None] = {}
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        tools = phase.get("preferred_tools")
        if not isinstance(tools, list):
            continue
        for tool in tools:
            name = str(tool or "").strip()
            if name:
                seen.setdefault(name)
    return tuple(seen)


def required_evidence_tools(workflow_contract: dict[str, Any] | None) -> tuple[str, ...]:
    """The evidence tools a contract declares as required (``required_evidence_tools``)."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    declared = contract.get(REQUIRED_EVIDENCE_TOOLS_KEY)
    if not isinstance(declared, list):
        return ()
    return tuple(dict.fromkeys(name for name in (str(tool or "").strip() for tool in declared) if name))


def _satisfied(workflow_id: str, reason: str, available: tuple[str, ...] = ()) -> WorkflowToolRequirementDecision:
    return WorkflowToolRequirementDecision(
        satisfied=True,
        status=EXECUTION_PROFILE_STATUS_ALLOWED,
        reason=reason,
        workflow_id=workflow_id,
        available_tools=available,
        inactive_connectors=(),
        inactive_connector_tools=(),
        policy_denied_tools=(),
    )


def evaluate_workflow_tool_requirements(
    *,
    workflow_contract: dict[str, Any] | None,
    project_config: dict[str, Any] | None,
) -> WorkflowToolRequirementDecision:
    """Check whether the project can execute at least one planned workflow tool."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    workflow_id = str(contract.get("workflow_id") or "").strip()
    required = required_evidence_tools(contract)
    if required:
        required_availability = _tool_availability(required, project_config)
        if required_availability.blocked:
            return _unsatisfied(workflow_id, required_availability, required=required)
    planned_tools = preferred_workflow_tools(contract)
    if not planned_tools:
        return _satisfied(workflow_id, "The workflow contract plans no explicit tools.")

    availability = _tool_availability(planned_tools, project_config)
    available = availability.available
    if available:
        return _satisfied(
            workflow_id,
            "At least one planned workflow tool is available for this project.",
            tuple(available),
        )

    return _unsatisfied(workflow_id, availability, required=())


@dataclass(frozen=True, slots=True)
class _ToolAvailability:
    available: tuple[str, ...]
    inactive_connectors: tuple[str, ...]
    inactive_connector_tools: tuple[str, ...]
    policy_denied_tools: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.inactive_connector_tools or self.policy_denied_tools)


def _tool_availability(tool_names: tuple[str, ...], project_config: dict[str, Any] | None) -> _ToolAvailability:
    available: list[str] = []
    inactive_connectors: dict[str, None] = {}
    inactive_connector_tools: list[str] = []
    policy_denied_tools: list[str] = []
    for tool_name in tool_names:
        visibility = tool_visibility_decision(tool_name, project_config)
        if not visibility.visible:
            inactive_connector_tools.append(tool_name)
            connector = str(visibility.connector or "").strip()
            if connector:
                inactive_connectors.setdefault(connector)
            continue
        policy = tool_project_policy_decision(tool_name, project_config)
        if not policy.allowed:
            policy_denied_tools.append(tool_name)
            continue
        available.append(tool_name)
    return _ToolAvailability(
        available=tuple(available),
        inactive_connectors=tuple(sorted(inactive_connectors)),
        inactive_connector_tools=tuple(inactive_connector_tools),
        policy_denied_tools=tuple(policy_denied_tools),
    )


def _unsatisfied(
    workflow_id: str, availability: _ToolAvailability, *, required: tuple[str, ...]
) -> WorkflowToolRequirementDecision:
    workflow_label = f"workflow '{workflow_id}'" if workflow_id else "the selected workflow"
    subject = (
        f"Evidence tools required by {workflow_label} ({', '.join(required)}) are unavailable."
        if required
        else f"All tools planned by {workflow_label} are unavailable."
    )
    if availability.inactive_connectors:
        connectors = ", ".join(availability.inactive_connectors)
        reason = f"{subject} Required connector(s) not active for this project: {connectors}."
        if availability.policy_denied_tools:
            denied = ", ".join(sorted(availability.policy_denied_tools))
            reason += f" Additionally denied by project tool policy: {denied}."
        status, reason_code = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION, REASON_CODE_CONNECTOR_INACTIVE
    else:
        reason = f"{subject} Denied by the project tool policy: {', '.join(sorted(availability.policy_denied_tools))}."
        status, reason_code = EXECUTION_PROFILE_STATUS_DENIED, REASON_CODE_TOOL_POLICY_DENIED
    return WorkflowToolRequirementDecision(
        satisfied=False,
        status=status,
        reason=reason,
        workflow_id=workflow_id,
        available_tools=availability.available if required else (),
        inactive_connectors=availability.inactive_connectors,
        inactive_connector_tools=availability.inactive_connector_tools,
        policy_denied_tools=availability.policy_denied_tools,
        reason_code=reason_code,
        required_tools=required,
    )


def apply_requirement_decision_to_profile(
    execution_profile: dict[str, Any],
    decision: WorkflowToolRequirementDecision,
) -> dict[str, Any]:
    """Return the profile metadata downgraded by an unsatisfied requirement decision.

    Only an ``allowed`` profile is downgraded; a profile that is already blocked
    keeps its original, more specific decision. The original status is preserved
    inside the requirement metadata for auditability.
    """
    profile = dict(execution_profile or {})
    requirement_metadata = decision.to_metadata()
    requirement_metadata["previous_status"] = profile.get("status")
    requirement_metadata["previous_decision_source"] = profile.get("decision_source")
    profile["requirements"] = requirement_metadata
    if decision.satisfied or profile.get("status") != EXECUTION_PROFILE_STATUS_ALLOWED:
        return profile
    profile["status"] = decision.status
    profile["decision_source"] = REQUIREMENT_DECISION_SOURCE
    profile["reason"] = decision.reason
    profile["reason_code"] = decision.reason_code or None
    return profile


__all__ = [
    "REASON_CODE_CONNECTOR_INACTIVE",
    "REASON_CODE_TOOL_POLICY_DENIED",
    "REQUIRED_EVIDENCE_TOOLS_KEY",
    "REQUIREMENT_DECISION_SOURCE",
    "WorkflowToolRequirementDecision",
    "apply_requirement_decision_to_profile",
    "evaluate_workflow_tool_requirements",
    "preferred_workflow_tools",
    "required_evidence_tools",
]
