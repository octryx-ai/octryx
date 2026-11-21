"""One contract per selected workflow, the same on the strategy and the loop path.

:func:`build_selected_workflow_contract` is the only builder of a selected workflow's contract
for a turn. ``resolve_execution_strategy`` and the standard loop setup (``_loop_setup``) call it
with the turn's routing resolution, so a selection yields one contract whichever path reads it.

Precedence, applied by :func:`apply_selected_definition` to the family builder's output when a
workflow-run phase is selected (its inline definition, ``source=db``, ``status=matched``):

1. **Builder output is the base.** The family builder reads the definition's configured contract
   (``selected_workflow_analysis``) and interprets the fields it owns (the knowledge query
   style). Its derived parameters (topic, evidence contract, phases, ``workflow_variant``, ...)
   are kept; on a key both carry, the builder's value stands.
2. **Consumed fields stay with the builder.** A configured field the family builder consumes
   (:data:`CONSUMED_DEFINITION_FIELDS`) is never copied back: the builder's result, a value or
   its deliberate absence (a refused value), is the contract.
3. **Other configured fields are carried through** unchanged (``allowed_tools``,
   ``source_steps``, ``when_to_use``, ``routing_intent``, ...).
4. **Definition governance wins** over the builder: :data:`DEFINITION_GOVERNED_FIELDS`.
5. **Provenance from the routing resolution** is set last: ``workflow_class``,
   ``workflow_contract_source`` (``db_routing_policy``), ``workflow_routing_policy_id``,
   ``workflow_routing_policy_version_id``, ``workflow_routing_policy_matched_group_id``.

The definition's tool policy and safety constraints are not contract fields: they stay on the
routing resolution, where the tool surface (``run_context_tool_policy.apply_routing_tool_policy``)
and the strategy (``resolve_workflow_routing_policy_intent_override``) read them.
"""

from __future__ import annotations

import copy
from typing import Any

from ..workflow_routing.workflow_selection import selected_workflow_analysis
from .registry import build_task_workflow_contract

DB_ROUTING_CONTRACT_SOURCE = "db_routing_policy"

# Governance a published definition owns: its value replaces a builder's value.
DEFINITION_GOVERNED_FIELDS = frozenset(
    {
        "allowed_tools",
        "capability_class",
        "requires_live_evidence",
        "requires_sources",
        "source_steps",
        "tool_selection_mode",
    }
)

# Configured fields a family builder consumes; its contract carries the interpreted result only.
CONSUMED_DEFINITION_FIELDS: dict[str, frozenset[str]] = {
    "knowledge_request": frozenset({"knowledge_query_style"}),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _configured(value: Any) -> bool:
    return value not in (None, "", [], {})


def is_matched_db_definition(routing_resolution: Any) -> bool:
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    return resolution.get("source") == "db" and resolution.get("status") == "matched"


def apply_selected_definition(built_contract: dict[str, Any] | None, routing_resolution: Any) -> dict[str, Any]:
    """The builder's contract with the selected DB definition's fields, by the module's precedence."""
    contract = dict(built_contract or {})
    if not contract or not is_matched_db_definition(routing_resolution):
        return contract
    resolution: dict[str, Any] = routing_resolution
    configured = resolution.get("workflow_contract")
    configured = configured if isinstance(configured, dict) else {}
    consumed = CONSUMED_DEFINITION_FIELDS.get(_text(contract.get("workflow_id")), frozenset())
    for key, value in configured.items():
        if key == "workflow_id" or key in consumed or not _configured(value):
            continue
        if key in DEFINITION_GOVERNED_FIELDS or key not in contract:
            contract[key] = copy.deepcopy(value)
    workflow_class = _text(resolution.get("workflow_class")) or _text(configured.get("workflow_class"))
    if workflow_class:
        contract["workflow_class"] = workflow_class
    contract["workflow_contract_source"] = DB_ROUTING_CONTRACT_SOURCE
    contract["workflow_routing_policy_id"] = resolution.get("policy_id")
    contract["workflow_routing_policy_version_id"] = resolution.get("policy_version_id")
    contract["workflow_routing_policy_matched_group_id"] = resolution.get("matched_group_id")
    return contract


def build_selected_workflow_contract(
    user_message: str,
    *,
    request_analysis: dict[str, Any] | None,
    routing_resolution: Any,
    route_reason: str = "",
    project_id: str | None = None,
    capability_type: str | None = None,
    workflow_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The contract of the workflow ``routing_resolution`` selects, or ``{}`` without a selection.

    ``workflow_decisions`` (the session's recorded closed decisions) reach the family builder the
    same way on every path.
    """
    contract = build_task_workflow_contract(
        user_message,
        request_analysis=selected_workflow_analysis(
            request_analysis,
            routing_resolution,
            workflow_decisions=workflow_decisions,
        ),
        route_reason=route_reason,
        project_id=project_id,
        capability_type=capability_type,
    )
    return apply_selected_definition(contract, routing_resolution)


__all__ = [
    "CONSUMED_DEFINITION_FIELDS",
    "DB_ROUTING_CONTRACT_SOURCE",
    "DEFINITION_GOVERNED_FIELDS",
    "apply_selected_definition",
    "build_selected_workflow_contract",
    "is_matched_db_definition",
]
