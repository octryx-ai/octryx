"""The turn's workflow selection, read from its routing resolution.

The routing resolution (``explicit_selection.resolve_workflow_selection_for_turn``) is the
only thing that selects a workflow family for a turn. This module reads it into one closed
:class:`WorkflowSelection`; the execution strategy and the standard loop build a workflow
contract only for a ``selected`` workflow, and only for that one. No prompt text is read here
or downstream to pick a family.

States (closed):

- ``selected``: the current phase of the session's workflow run, or a platform service's own
  selection (``platform_selection``).
- ``none``: no workflow. The user chose "no workflow", the proposal found nothing or is
  disabled, or no routing resolution at all.
- ``unknown_key``: the ``workflow_key`` does not resolve to a published workflow. The
  execution profile answers ``needs_clarification``.
- ``needs_confirmation``: a proposed workflow waits for the user; the execution gate holds
  the turn.
- ``project_inactive``: the turn's Workspace is deleted or archived; the profile denies it.

Only ``selected`` carries a ``workflow_id``. Every state carries a closed ``reason_code``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..project_activity import PROJECT_INACTIVE
from .platform_selection import PLATFORM_WORKFLOW_SELECTION_SOURCE, PLATFORM_WORKFLOW_SELECTION_STATUS
from .proposal_states import (
    STATUS_DISABLED,
    STATUS_NEEDS_CONFIRMATION,
    WORKFLOW_PROPOSAL_KEY,
    WORKFLOW_PROPOSAL_SOURCE,
)

# The explicit-selection resolution's source/status (``explicit_selection``), repeated here so
# this module stays models-free: the execution profile reads it (a test pins the equality).
EXPLICIT_WORKFLOW_SELECTION_SOURCE = "explicit_workflow_key"
EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY = "unknown_key"

WORKFLOW_SELECTION_METADATA_KEY = "workflow_selection"
WORKFLOW_SELECTION_VERSION = "workflow_selection.v1"
# The request-analysis key that carries the routing resolution into the contract builder.
ROUTING_RESOLUTION_KEY = "workflow_routing_policy_resolution"
# The request-analysis key that carries the session's recorded workflow decisions into the contract builder.
WORKFLOW_DECISIONS_ANALYSIS_KEY = "workflow_decisions"

SELECTION_SELECTED = "selected"
SELECTION_NONE = "none"
SELECTION_UNKNOWN_KEY = "unknown_key"
SELECTION_NEEDS_CONFIRMATION = "needs_confirmation"
SELECTION_PROJECT_INACTIVE = "project_inactive"
SELECTION_STATES = frozenset(
    {
        SELECTION_SELECTED,
        SELECTION_NONE,
        SELECTION_UNKNOWN_KEY,
        SELECTION_NEEDS_CONFIRMATION,
        SELECTION_PROJECT_INACTIVE,
    }
)

REASON_PLATFORM_SERVICE = "platform_service"
# A caller handed the contract builder an explicit contract and no routing resolution.
REASON_EXPLICIT_CONTRACT = "explicit_contract"
REASON_USER_SELECTED_NO_WORKFLOW = "user_selected_no_workflow"
REASON_PROPOSAL_NONE = "proposal_none"
REASON_PROPOSAL_DISABLED = "proposal_disabled"
REASON_NO_WORKFLOW_SELECTED = "no_workflow_selected"
REASON_NO_ROUTING_RESOLUTION = "no_routing_resolution"
REASON_UNKNOWN_WORKFLOW_KEY = "unknown_workflow_key"
REASON_PROPOSAL_NEEDS_CONFIRMATION = "proposal_needs_confirmation"
REASON_PROJECT_INACTIVE = "project_inactive"
# The session follows an active workflow run; the run's current phase is the selection.
REASON_WORKFLOW_RUN = "workflow_run"
WORKFLOW_RUN_SELECTION_SOURCE = "workflow_run"
SELECTION_REASON_CODES = frozenset(
    {
        REASON_PLATFORM_SERVICE,
        REASON_EXPLICIT_CONTRACT,
        REASON_USER_SELECTED_NO_WORKFLOW,
        REASON_PROPOSAL_NONE,
        REASON_PROPOSAL_DISABLED,
        REASON_NO_WORKFLOW_SELECTED,
        REASON_NO_ROUTING_RESOLUTION,
        REASON_UNKNOWN_WORKFLOW_KEY,
        REASON_PROPOSAL_NEEDS_CONFIRMATION,
        REASON_PROJECT_INACTIVE,
        REASON_WORKFLOW_RUN,
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowSelection:
    state: str
    reason_code: str
    workflow_id: str = ""
    workflow_key: str = ""

    @property
    def selected(self) -> bool:
        return self.state == SELECTION_SELECTED and bool(self.workflow_id)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WORKFLOW_SELECTION_VERSION,
            "state": self.state,
            "reason_code": self.reason_code,
            "workflow_id": self.workflow_id or None,
            "workflow_key": self.workflow_key or None,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contract(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _selected(resolution: dict[str, Any], reason_code: str) -> WorkflowSelection:
    configured = _contract(resolution.get("workflow_contract"))
    workflow_id = _text(resolution.get("workflow_id")) or _text(configured.get("workflow_id"))
    if not workflow_id:
        return WorkflowSelection(SELECTION_NONE, REASON_NO_WORKFLOW_SELECTED)
    return WorkflowSelection(SELECTION_SELECTED, reason_code, workflow_id, _text(resolution.get("workflow_key")))


def _no_workflow(resolution: dict[str, Any]) -> WorkflowSelection:
    proposal = resolution.get(WORKFLOW_PROPOSAL_KEY)
    proposal = proposal if isinstance(proposal, dict) else {}
    if proposal.get("reason_code") == REASON_USER_SELECTED_NO_WORKFLOW:
        return WorkflowSelection(SELECTION_NONE, REASON_USER_SELECTED_NO_WORKFLOW)
    if proposal.get("status") == STATUS_DISABLED:
        return WorkflowSelection(SELECTION_NONE, REASON_PROPOSAL_DISABLED)
    if proposal:
        return WorkflowSelection(SELECTION_NONE, REASON_PROPOSAL_NONE)
    return WorkflowSelection(SELECTION_NONE, REASON_NO_WORKFLOW_SELECTED)


def workflow_selection_from_resolution(resolution: Any) -> WorkflowSelection:
    """The closed selection a routing resolution makes; never reads the prompt."""
    if not isinstance(resolution, dict) or not resolution:
        return WorkflowSelection(SELECTION_NONE, REASON_NO_ROUTING_RESOLUTION)
    source = _text(resolution.get("source"))
    status = _text(resolution.get("status"))
    if status == PROJECT_INACTIVE:
        return WorkflowSelection(SELECTION_PROJECT_INACTIVE, REASON_PROJECT_INACTIVE)
    if source == EXPLICIT_WORKFLOW_SELECTION_SOURCE and status == EXPLICIT_WORKFLOW_SELECTION_STATUS_UNKNOWN_KEY:
        return WorkflowSelection(
            SELECTION_UNKNOWN_KEY, REASON_UNKNOWN_WORKFLOW_KEY, workflow_key=_text(resolution.get("workflow_key"))
        )
    if source == WORKFLOW_PROPOSAL_SOURCE and status == STATUS_NEEDS_CONFIRMATION:
        return WorkflowSelection(SELECTION_NEEDS_CONFIRMATION, REASON_PROPOSAL_NEEDS_CONFIRMATION)
    if source == PLATFORM_WORKFLOW_SELECTION_SOURCE and status == PLATFORM_WORKFLOW_SELECTION_STATUS:
        return _selected(resolution, REASON_PLATFORM_SERVICE)
    if source == "db" and status == "matched" and _text(resolution.get("selection_source")) == (
        WORKFLOW_RUN_SELECTION_SOURCE
    ):
        return _selected(resolution, REASON_WORKFLOW_RUN)
    # Everything else selects no workflow: the no-selection shape, with or without a proposal record.
    return _no_workflow(resolution)


def workflow_selection_from_analysis(request_analysis: Any) -> WorkflowSelection:
    """The selection the contract builder sees.

    The routing resolution decides whenever it is present. Without one, an explicit
    ``workflow_contract`` the caller put into the analysis is the selection (a governed tool
    or a test names its workflow this way); nothing else selects a family.
    """
    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    resolution = analysis.get(ROUTING_RESOLUTION_KEY)
    if isinstance(resolution, dict) and resolution:
        return workflow_selection_from_resolution(resolution)
    workflow_id = _text(_contract(analysis.get("workflow_contract")).get("workflow_id"))
    if workflow_id:
        return WorkflowSelection(SELECTION_SELECTED, REASON_EXPLICIT_CONTRACT, workflow_id)
    return WorkflowSelection(SELECTION_NONE, REASON_NO_ROUTING_RESOLUTION)


def selected_workflow_analysis(
    request_analysis: dict[str, Any] | None,
    resolution: Any,
    *,
    workflow_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """A copy of ``request_analysis`` that carries the resolution and the selected contract.

    Both builders of a turn's contract (the execution strategy and the standard loop) call
    the contract builder with this copy, so a selected workflow's configured contract (from
    its published definition or the platform service) reaches the family's contract builder
    the same way on both paths, and a turn without a selection carries no contract at all.

    ``workflow_decisions`` are the session's recorded closed decisions; they reach the builder
    the same way on both paths.
    """
    analysis = dict(request_analysis or {})
    analysis.pop("workflow_contract", None)
    if workflow_decisions:
        analysis[WORKFLOW_DECISIONS_ANALYSIS_KEY] = dict(workflow_decisions)
    if not isinstance(resolution, dict) or not resolution:
        return analysis
    analysis[ROUTING_RESOLUTION_KEY] = dict(resolution)
    selection = workflow_selection_from_resolution(resolution)
    if selection.selected:
        configured = _contract(resolution.get("workflow_contract"))
        configured["workflow_id"] = selection.workflow_id
        analysis["workflow_contract"] = configured
    return analysis


__all__ = [
    "REASON_EXPLICIT_CONTRACT",
    "REASON_NO_ROUTING_RESOLUTION",
    "REASON_NO_WORKFLOW_SELECTED",
    "REASON_PLATFORM_SERVICE",
    "REASON_PROJECT_INACTIVE",
    "REASON_PROPOSAL_DISABLED",
    "REASON_PROPOSAL_NEEDS_CONFIRMATION",
    "REASON_PROPOSAL_NONE",
    "REASON_UNKNOWN_WORKFLOW_KEY",
    "REASON_USER_SELECTED_NO_WORKFLOW",
    "REASON_WORKFLOW_RUN",
    "ROUTING_RESOLUTION_KEY",
    "SELECTION_NEEDS_CONFIRMATION",
    "SELECTION_NONE",
    "SELECTION_PROJECT_INACTIVE",
    "SELECTION_REASON_CODES",
    "SELECTION_SELECTED",
    "SELECTION_STATES",
    "SELECTION_UNKNOWN_KEY",
    "WORKFLOW_DECISIONS_ANALYSIS_KEY",
    "WORKFLOW_RUN_SELECTION_SOURCE",
    "WORKFLOW_SELECTION_METADATA_KEY",
    "WORKFLOW_SELECTION_VERSION",
    "WorkflowSelection",
    "selected_workflow_analysis",
    "workflow_selection_from_analysis",
    "workflow_selection_from_resolution",
]
