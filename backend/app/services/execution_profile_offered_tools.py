"""The offered-tool check of a selected workflow definition, before the model call.

The requirements check (``execution_profile_requirements.py``) checks what a definition *plans* against the
Workspace: visibility and project tool policy of each tool name. It never sees the tool
surface the turn actually offers the model. A Workspace-scoped ``jira_release_status`` definition allowlisting
three Jira tools, with Jira active, could pass that check and still run with zero tools, because
the turn's context plan withheld all tools; the model then writes fake tool calls as text and that text goes
out as the answer.

This check closes that silent path. After run preparation built the offered tool
definitions, a turn whose selected definition (``source="db"``, ``status="matched"``)
declares tools must offer them:

- every ``required_evidence_tools`` entry must be offered;
- at least one tool of the definition's ``tool_policy.allowlist`` must be offered, not
  counting the common meta tools every narrowed surface carries (``instruction_get``,
  ``get_current_time`` ...), which answer nothing on their own.

Planned phase tools are not checked here: some families (``generic_diagram``) add their
planned tools inside the loop, so they are not in the prepared set; the requirements check
covers their availability.

An unsatisfied check turns an ``allowed`` profile into an explicit state before the loop,
with a reason code naming the cause of the first unoffered tool class found:

- ``connector_not_active_for_project`` → ``needs_configuration``
- ``definition_tool_unknown`` (the definition names a tool the platform does not have)
  → ``needs_configuration``
- ``tool_denied_by_project_policy`` (every missing tool is denied by policy) → ``denied``
- ``definition_tools_not_offered`` (visible and allowed, still not offered: the turn's
  tool surface withheld them) → ``needs_configuration``

The runtime execution gate (``services/session/execution_gate.py``) enforces the status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.definitions import get_all_definitions
from ..tools.visibility import tool_visibility_decision
from .execution_profile_requirements import required_evidence_tools
from .execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)
from .tool_access_policy import tool_project_policy_decision
from .workflow_routing.tool_policy import normalized_tool_policy

OFFERED_TOOLS_DECISION_SOURCE = "workflow_offered_tools"
OFFERED_TOOLS_METADATA_KEY = "offered_tools"
REASON_CODE_CONNECTOR_INACTIVE = "connector_not_active_for_project"
REASON_CODE_TOOL_POLICY_DENIED = "tool_denied_by_project_policy"
REASON_CODE_DEFINITION_TOOL_UNKNOWN = "definition_tool_unknown"
REASON_CODE_DEFINITION_TOOLS_NOT_OFFERED = "definition_tools_not_offered"

# Meta tools every narrowed surface carries (``agent/core/context/tool_families.COMMON_READ_ONLY_TOOLS``
# plus the context-prompt meta tool): offering only these is offering nothing the definition asked for.
_META_TOOL_NAMES = frozenset(
    {"get_current_time", "get_system_context", "instruction_get", "select_workflow", "skill_search", "skill_get"}
)


@dataclass(frozen=True, slots=True)
class OfferedToolDecision:
    """Whether the offered tool surface carries what the selected definition declares."""

    satisfied: bool
    status: str
    reason: str
    reason_code: str
    workflow_id: str
    offered_definition_tools: tuple[str, ...] = ()
    missing_required_tools: tuple[str, ...] = ()
    unknown_tools: tuple[str, ...] = ()
    inactive_connectors: tuple[str, ...] = ()
    inactive_connector_tools: tuple[str, ...] = ()
    policy_denied_tools: tuple[str, ...] = ()
    withheld_tools: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "status": self.status,
            "reason": self.reason,
            "reason_code": self.reason_code or None,
            "workflow_id": self.workflow_id or None,
            "offered_definition_tools": list(self.offered_definition_tools),
            "missing_required_tools": list(self.missing_required_tools),
            "unknown_tools": list(self.unknown_tools),
            "inactive_connectors": list(self.inactive_connectors),
            "inactive_connector_tools": list(self.inactive_connector_tools),
            "policy_denied_tools": list(self.policy_denied_tools),
            "withheld_tools": list(self.withheld_tools),
        }


def _offered_names(tool_definitions: list[dict[str, Any]] | None) -> set[str]:
    names: set[str] = set()
    for definition in tool_definitions or []:
        function = definition.get("function") if isinstance(definition, dict) else None
        name = str((function or {}).get("name") or "").strip() if isinstance(function, dict) else ""
        if name:
            names.add(name)
    return names


def _selected_definition(routing_resolution: dict[str, Any] | None) -> dict[str, Any] | None:
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    if resolution.get("source") != "db" or resolution.get("status") != "matched":
        return None
    return resolution


def _satisfied(workflow_id: str, reason: str, offered: tuple[str, ...] = ()) -> OfferedToolDecision:
    return OfferedToolDecision(
        satisfied=True,
        status=EXECUTION_PROFILE_STATUS_ALLOWED,
        reason=reason,
        reason_code="",
        workflow_id=workflow_id,
        offered_definition_tools=offered,
    )


def evaluate_offered_definition_tools(
    *,
    routing_resolution: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    tool_definitions: list[dict[str, Any]] | None,
    project_config: dict[str, Any] | None,
) -> OfferedToolDecision:
    """Check the prepared tool surface against the selected definition's declared tools."""
    resolution = _selected_definition(routing_resolution)
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    workflow_id = str(contract.get("workflow_id") or (resolution or {}).get("workflow_id") or "").strip()
    if resolution is None:
        return _satisfied(workflow_id, "No workflow definition is selected for this turn.")
    offered = _offered_names(tool_definitions)
    configured_contract = resolution.get("workflow_contract")
    required = tuple(dict.fromkeys([*required_evidence_tools(contract), *required_evidence_tools(configured_contract)]))
    policy_allowlist = normalized_tool_policy(resolution.get("tool_policy"))["allowlist"]
    allowlist = tuple(name for name in policy_allowlist if name not in _META_TOOL_NAMES)
    missing_required = tuple(name for name in required if name not in offered)
    offered_allowlisted = tuple(name for name in allowlist if name in offered)
    if not missing_required and (offered_allowlisted or not allowlist):
        reason = "The turn offers the tools its workflow definition declares."
        return _satisfied(workflow_id, reason, offered_allowlisted)
    unoffered = missing_required if missing_required else allowlist
    return _unsatisfied(workflow_id, unoffered, missing_required, project_config)


def _unsatisfied(
    workflow_id: str,
    unoffered: tuple[str, ...],
    missing_required: tuple[str, ...],
    project_config: dict[str, Any] | None,
) -> OfferedToolDecision:
    known = get_all_definitions()
    unknown: list[str] = []
    inactive_tools: list[str] = []
    inactive_connectors: dict[str, None] = {}
    denied: list[str] = []
    withheld: list[str] = []
    for name in unoffered:
        if name not in known:
            unknown.append(name)
            continue
        visibility = tool_visibility_decision(name, project_config)
        if not visibility.visible:
            inactive_tools.append(name)
            if visibility.connector:
                inactive_connectors.setdefault(str(visibility.connector))
            continue
        if not tool_project_policy_decision(name, project_config).allowed:
            denied.append(name)
            continue
        withheld.append(name)
    label = f"workflow '{workflow_id}'" if workflow_id else "the selected workflow"
    subject = (
        f"Evidence tools required by {label} are not offered to the model: {', '.join(missing_required)}."
        if missing_required
        else f"None of the tools {label} allows is offered to the model: {', '.join(unoffered)}."
    )
    status = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    if inactive_tools:
        reason_code = REASON_CODE_CONNECTOR_INACTIVE
        cause = f"Connector(s) not active for this Workspace: {', '.join(sorted(inactive_connectors))}."
    elif unknown:
        reason_code = REASON_CODE_DEFINITION_TOOL_UNKNOWN
        cause = f"The definition names tools the platform does not have: {', '.join(sorted(unknown))}."
    elif denied and not withheld:
        reason_code, status = REASON_CODE_TOOL_POLICY_DENIED, EXECUTION_PROFILE_STATUS_DENIED
        cause = f"Denied by the Workspace tool policy: {', '.join(sorted(denied))}."
    else:
        reason_code = REASON_CODE_DEFINITION_TOOLS_NOT_OFFERED
        cause = f"The turn's tool surface withheld: {', '.join(sorted(withheld or denied))}."
    return OfferedToolDecision(
        satisfied=False,
        status=status,
        reason=f"{subject} {cause}",
        reason_code=reason_code,
        workflow_id=workflow_id,
        missing_required_tools=missing_required,
        unknown_tools=tuple(sorted(unknown)),
        inactive_connectors=tuple(sorted(inactive_connectors)),
        inactive_connector_tools=tuple(inactive_tools),
        policy_denied_tools=tuple(denied),
        withheld_tools=tuple(withheld),
    )


def apply_offered_tool_decision_to_profile(
    execution_profile: dict[str, Any] | None,
    decision: OfferedToolDecision,
) -> dict[str, Any]:
    """The profile with the decision recorded; an unsatisfied decision blocks an ``allowed`` profile.

    A profile that is already blocked keeps its own, earlier decision (requirements check or routing).
    """
    profile = dict(execution_profile or {})
    requirements = dict(profile.get("requirements") or {})
    requirements[OFFERED_TOOLS_METADATA_KEY] = decision.to_metadata()
    profile["requirements"] = requirements
    if decision.satisfied or profile.get("status") != EXECUTION_PROFILE_STATUS_ALLOWED:
        return profile
    requirements[OFFERED_TOOLS_METADATA_KEY]["previous_status"] = profile.get("status")
    requirements[OFFERED_TOOLS_METADATA_KEY]["previous_decision_source"] = profile.get("decision_source")
    profile["status"] = decision.status
    profile["decision_source"] = OFFERED_TOOLS_DECISION_SOURCE
    profile["reason"] = decision.reason
    profile["reason_code"] = decision.reason_code
    return profile


__all__ = [
    "OFFERED_TOOLS_DECISION_SOURCE",
    "OFFERED_TOOLS_METADATA_KEY",
    "REASON_CODE_CONNECTOR_INACTIVE",
    "REASON_CODE_DEFINITION_TOOLS_NOT_OFFERED",
    "REASON_CODE_DEFINITION_TOOL_UNKNOWN",
    "REASON_CODE_TOOL_POLICY_DENIED",
    "OfferedToolDecision",
    "apply_offered_tool_decision_to_profile",
    "evaluate_offered_definition_tools",
]
