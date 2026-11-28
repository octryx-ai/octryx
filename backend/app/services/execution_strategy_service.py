"""Top-level execution strategy routing for task-oriented chat entrypoints. Explicit-first: the platform never guesses
user intent from prompt text."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .agent_mode import DEFAULT_AGENT_MODE_KEY
from .execution_strategy_intent import (
    _effective_agent_type,
    _Routing,
    _routing_for_turn,
)
from .request_analysis import build_request_analysis
from .workflow_contracts.selected_contract import build_selected_workflow_contract
from .workflow_routing.workflow_selection import (
    SELECTION_NONE,
    SELECTION_SELECTED,
    WorkflowSelection,
    workflow_selection_from_resolution,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionStrategyDecision:
    execution_strategy: str
    execution_strategy_reason: str
    routing_intent: str
    routing_reason: str
    routing_intent_confidence: float
    routing_intent_source: str
    effective_agent_type: str
    workflow_id: str
    workflow_contract: dict[str, Any]
    # The closed workflow selection the routing resolution made (``WorkflowSelection``).
    workflow_selection: dict[str, Any] = field(default_factory=dict)


def resolve_execution_strategy(
    *,
    prompt: str,
    requested_agent_type: str,
    project_id: str | None = None,
    agent_id: str = "",
    agent_type_explicit: bool = False,
    allow_workflow_contracts: bool = True,
    routing_intent_override: str | None = None,
    routing_reason_override: str | None = None,
    support_request_signature: bool = False,
    workflow_routing_policy_resolution: dict[str, Any] | None = None,
    workflow_decisions: dict[str, str] | None = None,
) -> ExecutionStrategyDecision:
    # Inputs of this turn only: no stored routing hint carries into this turn, and no keyword classifier decides.
    clean_prompt = str(prompt or "").strip()
    normalized_agent_type = str(requested_agent_type or DEFAULT_AGENT_MODE_KEY).strip() or DEFAULT_AGENT_MODE_KEY
    routing = _routing_for_turn(
        clean_prompt=clean_prompt, normalized_agent_type_key=normalized_agent_type.lower(),
        agent_type_explicit=agent_type_explicit, routing_intent_override=routing_intent_override,
        routing_reason_override=routing_reason_override, support_request_signature=support_request_signature,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution,
    )
    explicit_target_selected = bool(str(agent_id or "").strip())
    effective_agent_type, routing = _effective_agent_type(
        routing, clean_prompt=clean_prompt, normalized_agent_type=normalized_agent_type, agent_id=agent_id,
        agent_type_explicit=agent_type_explicit, explicit_target_selected=explicit_target_selected,
    )
    selection = workflow_selection_from_resolution(workflow_routing_policy_resolution)
    workflow_contract = _selected_workflow_contract(
        selection, clean_prompt=clean_prompt, routing_reason=routing.reason,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution, project_id=project_id,
        capability_type=_capability_type_for_agent_type(effective_agent_type),
        workflow_decisions=workflow_decisions,
    )
    return _strategy_decision(
        selection, routing, workflow_contract=workflow_contract, allow_workflow_contracts=allow_workflow_contracts,
        explicit_target_selected=explicit_target_selected, effective_agent_type=effective_agent_type,
    )


def _selected_workflow_contract(
    selection: WorkflowSelection,
    *,
    clean_prompt: str,
    routing_reason: str,
    workflow_routing_policy_resolution: dict[str, Any] | None,
    project_id: str | None,
    capability_type: str,
    workflow_decisions: dict[str, str] | None,
) -> dict[str, Any]:
    # The workflow comes only from the routing resolution: a turn without a selected
    # workflow builds no contract, whatever its prompt says.
    workflow_contract: dict[str, Any] = {}
    if selection.state == SELECTION_SELECTED:
        # The same builder as the standard loop: one contract per selected workflow.
        request_analysis = build_request_analysis(clean_prompt, route_reason=routing_reason)
        workflow_contract = build_selected_workflow_contract(
            str(request_analysis.get("canonical_message") or clean_prompt or "").strip(),
            request_analysis=request_analysis,
            routing_resolution=workflow_routing_policy_resolution,
            route_reason=routing_reason,
            project_id=str(project_id or "").strip() or None,
            capability_type=capability_type,
            workflow_decisions=workflow_decisions,
        )
    return workflow_contract


def _strategy_decision(
    selection: WorkflowSelection,
    routing: _Routing,
    *,
    workflow_contract: dict[str, Any],
    allow_workflow_contracts: bool,
    explicit_target_selected: bool,
    effective_agent_type: str,
) -> ExecutionStrategyDecision:
    # A disabled workflow contract falls back to direct.
    workflow_id = str(workflow_contract.get("workflow_id") or "").strip()
    common = {
        "routing_intent": routing.intent,
        "routing_reason": routing.reason,
        "routing_intent_confidence": routing.confidence,
        "routing_intent_source": routing.source,
        "effective_agent_type": effective_agent_type,
        "workflow_selection": selection.to_metadata(),
    }
    if workflow_id and not allow_workflow_contracts:
        return ExecutionStrategyDecision(
            execution_strategy="direct",
            execution_strategy_reason="strategy:direct_workflow_disabled",
            workflow_id="",
            workflow_contract={},
            **common,
        )
    if explicit_target_selected:
        strategy, reason = "specialist", "strategy:explicit_target"
    else:
        strategy, reason = "direct", "strategy:direct_default"
        if selection.state not in {SELECTION_SELECTED, SELECTION_NONE}:
            # An unresolved selection (unknown key, pending proposal, inactive Workspace) is
            # its own reason; the execution profile and the gate decide whether the turn runs.
            reason = f"strategy:workflow_selection_{selection.state}"
        elif effective_agent_type == "coding":
            reason = "strategy:direct_coding"
        elif routing.intent == "operations":
            reason = "strategy:direct_operations"
    return ExecutionStrategyDecision(
        execution_strategy=strategy,
        execution_strategy_reason=reason,
        workflow_id=workflow_id,
        workflow_contract=workflow_contract,
        **common,
    )


def _capability_type_for_agent_type(agent_type: str) -> str:
    normalized = str(agent_type or DEFAULT_AGENT_MODE_KEY).strip().lower() or DEFAULT_AGENT_MODE_KEY
    if normalized in {"change", "coding"}:
        return "change"
    return normalized
