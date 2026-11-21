"""Turn routing and execution profile resolution during run preparation.

Extracted from ``run_context.prepare_agent_run`` as the first seam of the
run-context decomposition: this module owns how a runtime turn resolves its
execution strategy, records routing metadata on the session, and rebuilds the
execution profile envelope that the runtime execution gate enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.execution_strategy_intent import (
    resolve_workflow_routing_policy_intent_override,
    support_request_signature_applies,
)

from ....services.execution_profile_service import build_execution_profile
from ....services.execution_strategy_service import ExecutionStrategyDecision, resolve_execution_strategy
from ....services.run_capability import RunCapabilityResolution, resolve_run_capability
from ....services.run_capability.escalation import record_capability_escalation
from ....services.workflow_contracts.decisions import recorded_workflow_decisions
from ....services.workflow_routing.proposal_usage import record_workflow_proposal_usage
from ....services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY


@dataclass(frozen=True, slots=True)
class TurnRoutingResolution:
    strategy_decision: ExecutionStrategyDecision
    effective_agent_type: str
    expected_workflow_id: str
    execution_profile_metadata: dict[str, Any]
    run_capability: RunCapabilityResolution


async def _resolve_run_capability(
    db: Any,
    *,
    session_metadata: dict[str, Any],
    agent_type: str,
    agent_definition: dict | None,
    parent_session_id: str | None,
    session_id: str | None,
    user_id: str | None,
) -> RunCapabilityResolution:
    run_capability = await resolve_run_capability(
        db,
        session_metadata=session_metadata,
        routing_resolution=session_metadata.get(ROUTING_RESOLUTION_KEY),
        requested_agent_type=agent_type,
        agent_definition=agent_definition,
        parent_session_id=parent_session_id,
    )
    await record_capability_escalation(
        db, session_metadata=session_metadata, resolution=run_capability, user_id=user_id, session_id=session_id
    )
    # The pre-turn workflow proposal call is accounted here, where the session exists.
    await record_workflow_proposal_usage(db, session_metadata=session_metadata, session_id=session_id, user_id=user_id)
    return run_capability


async def _resolve_strategy(
    db: Any,
    *,
    session_metadata: dict[str, Any],
    user_message: str,
    run_agent_type: str,
    project_id: str | None,
    agent_definition: dict | None,
) -> ExecutionStrategyDecision:
    allow_workflow_contracts = session_metadata.get("allow_workflow_contracts")
    if allow_workflow_contracts is None:
        allow_workflow_contracts = True
    routing_intent_override, routing_reason_override = resolve_workflow_routing_policy_intent_override(
        workflow_routing_policy_resolution=session_metadata.get(ROUTING_RESOLUTION_KEY)
    )
    strategy_decision = resolve_execution_strategy(
        prompt=user_message,
        requested_agent_type=run_agent_type,
        project_id=project_id,
        # The platform default (the Assistant) is no explicit target: a plain turn stays direct.
        agent_id="" if session_metadata.get("agent_selection_source") == "platform_default" else str(
            (agent_definition or {}).get("id") or session_metadata.get("agent_definition_id") or "").strip(),
        agent_type_explicit=True,
        allow_workflow_contracts=bool(allow_workflow_contracts),
        routing_intent_override=routing_intent_override,
        routing_reason_override=routing_reason_override,
        # Evaluated for this turn's message and the current switch; routing hints
        # stored by preparation or an earlier turn never decide.
        support_request_signature=await support_request_signature_applies(user_message, db=db),
        workflow_routing_policy_resolution=session_metadata.get(ROUTING_RESOLUTION_KEY),
        workflow_decisions=recorded_workflow_decisions(session_metadata),
    )
    return strategy_decision


def _record_routing_metadata(session_metadata: dict[str, Any], strategy_decision: ExecutionStrategyDecision) -> str:
    """Record the routing decision on the session; returns the workflow the turn is expected to run."""
    session_metadata["routing_intent"] = strategy_decision.routing_intent
    session_metadata["routing_reason"] = strategy_decision.routing_reason
    session_metadata["routing_intent_confidence"] = strategy_decision.routing_intent_confidence
    session_metadata["routing_intent_source"] = strategy_decision.routing_intent_source
    session_metadata["execution_strategy"] = strategy_decision.execution_strategy
    session_metadata["execution_strategy_reason"] = strategy_decision.execution_strategy_reason
    if strategy_decision.workflow_id:
        session_metadata.setdefault("expected_workflow_id", strategy_decision.workflow_id)
    expected_workflow_id = str(session_metadata.get("expected_workflow_id") or strategy_decision.workflow_id or "")
    return expected_workflow_id


def _execution_profile_metadata(
    *,
    session_metadata: dict[str, Any],
    user_message: str,
    agent_type: str,
    effective_agent_type: str,
    expected_workflow_id: str,
    strategy_decision: ExecutionStrategyDecision,
    runtime_target_id: str | None,
    run_capability: RunCapabilityResolution,
) -> dict[str, Any]:
    existing_execution_profile = (
        session_metadata.get("execution_profile")
        if isinstance(session_metadata.get("execution_profile"), dict)
        else {}
    )
    return build_execution_profile(
        prompt=user_message,
        requested_agent_type=agent_type,
        effective_agent_type=effective_agent_type,
        execution_strategy=strategy_decision.execution_strategy,
        execution_strategy_reason=strategy_decision.execution_strategy_reason,
        routing_intent=strategy_decision.routing_intent,
        routing_reason=strategy_decision.routing_reason,
        routing_intent_confidence=strategy_decision.routing_intent_confidence,
        routing_intent_source=strategy_decision.routing_intent_source,
        workflow_id=expected_workflow_id,
        workflow_contract=strategy_decision.workflow_contract,
        agent_type_explicit=str(existing_execution_profile.get("decision_source") or "") == "explicit_ui_context",
        workflow_routing_policy_resolution=session_metadata.get(ROUTING_RESOLUTION_KEY),
        runtime_target_id=runtime_target_id,
        runtime_label=str(session_metadata.get("runtime_label") or "").strip() or None,
        capability=run_capability.to_metadata(),
        governed_origin=run_capability.declared_origin,
    ).to_metadata()


async def resolve_turn_routing_profile(
    *,
    db: Any,
    session_metadata: dict[str, Any],
    user_message: str,
    agent_type: str,
    project_id: str | None,
    agent_definition: dict | None,
    runtime_target_id: str | None,
    parent_session_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> TurnRoutingResolution:
    """Resolve the turn's execution strategy and refresh the session's profile envelope.

    Mutates ``session_metadata`` in place (routing fields, ``execution_profile``); the caller persists it.

    The run capability is decided first (``services/run_capability``): for a
    governed run it replaces the request's ``agent_type`` as the mode the strategy
    ladder, the workflow contract builder, and the tool surface see.
    """
    run_capability = await _resolve_run_capability(
        db,
        session_metadata=session_metadata,
        agent_type=agent_type,
        agent_definition=agent_definition,
        parent_session_id=parent_session_id,
        session_id=session_id,
        user_id=user_id,
    )
    run_agent_type = run_capability.effective_agent_type or agent_type
    strategy_decision = await _resolve_strategy(
        db,
        session_metadata=session_metadata,
        user_message=user_message,
        run_agent_type=run_agent_type,
        project_id=project_id,
        agent_definition=agent_definition,
    )
    effective_agent_type = str(strategy_decision.effective_agent_type or run_agent_type or "").strip() or run_agent_type
    expected_workflow_id = _record_routing_metadata(session_metadata, strategy_decision)
    execution_profile_metadata = _execution_profile_metadata(
        session_metadata=session_metadata,
        user_message=user_message,
        agent_type=agent_type,
        effective_agent_type=effective_agent_type,
        expected_workflow_id=expected_workflow_id,
        strategy_decision=strategy_decision,
        runtime_target_id=runtime_target_id,
        run_capability=run_capability,
    )
    # A router block persisted by an earlier turn must not be attributed to this run.
    session_metadata["execution_profile"] = execution_profile_metadata
    return TurnRoutingResolution(
        strategy_decision=strategy_decision,
        effective_agent_type=effective_agent_type,
        expected_workflow_id=expected_workflow_id,
        execution_profile_metadata=execution_profile_metadata,
        run_capability=run_capability,
    )


__all__ = [
    "TurnRoutingResolution",
    "resolve_turn_routing_profile",
]
