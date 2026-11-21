"""The routing half of turn preparation: workflow selection and execution strategy.

Moved unchanged from ``web/_helpers/chat_turn_prepare`` so both entry paths route a turn
the same way. Preparation makes no chat-model call: the workflow proposal is
resolved before the preparation lock (``workflow_routing/proposal_prefetch``) and handed
in; a model may still select a workflow inside the governed agent turn via the
``select_workflow`` catalog tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution_strategy_intent import (
    resolve_workflow_routing_policy_intent_override,
    support_request_signature_applies,
)

from ...models import Session as AgentSession
from ..agent_mode import resolve_agent_mode
from ..execution_strategy_service import ExecutionStrategyDecision, resolve_execution_strategy
from ..workflow_contracts.decisions import recorded_workflow_decisions
from ..workflow_routing.explicit_selection import resolve_workflow_selection_for_turn
from ..workflow_routing.proposal_prefetch import PrecomputedWorkflowProposal
from ..workflow_routing.workflow_selection import workflow_selection_from_resolution
from ..workflow_runs.binding import run_turn_resolution
from .turn_preparation import preserve_waiting_session_contract


@dataclass(slots=True)
class TurnRouting:
    policy_resolution: dict[str, Any]
    strategy_decision: ExecutionStrategyDecision
    routing_intent: str
    routing_reason: str
    effective_agent_type: str
    execution_strategy: str
    execution_strategy_reason: str
    expected_workflow_id: str
    selected_mode_key: str


def _turn_workflow_decisions(session: AgentSession | None, requested: dict[str, str] | None) -> dict[str, str]:
    recorded = recorded_workflow_decisions(session.metadata_ if session is not None else None)
    return {**recorded, **(requested or {})}


async def resolve_turn_routing(
    db: AsyncSession,
    *,
    clean_prompt: str,
    session: AgentSession | None,
    requested_agent_type: str,
    agent_type_explicit: bool,
    project_id: str,
    effective_project_id: str,
    agent_id: str,
    workflow_key: str,
    precomputed_proposal: PrecomputedWorkflowProposal | None,
    platform_workflow_service: str = "",
    workflow_decisions: dict[str, str] | None = None,
) -> TurnRouting:
    # The routing resolution is the turn's only workflow selection: a platform service's own
    # workflow, an explicit workflow_key, "no workflow", or (explicit mode) the proposal. The
    # strategy below builds a contract only for the workflow this resolution selects.
    turn_decisions = _turn_workflow_decisions(session, workflow_decisions)
    # A session bound to an active workflow run follows the run's current phase (or is held by it).
    run_resolution = await run_turn_resolution(db, session, user_message=clean_prompt)
    policy_resolution = run_resolution or await resolve_workflow_selection_for_turn(
        db,
        workflow_key=workflow_key,
        user_message=clean_prompt,
        project_id=effective_project_id or None,
        precomputed_proposal=precomputed_proposal,
        platform_workflow_service=platform_workflow_service,
    )
    support_request_signature = await support_request_signature_applies(clean_prompt, db=db)
    routing_intent_override, routing_reason_override = resolve_workflow_routing_policy_intent_override(
        workflow_routing_policy_resolution=policy_resolution
    )
    decision = resolve_execution_strategy(
        prompt=clean_prompt,
        requested_agent_type=requested_agent_type,
        project_id=project_id or None,
        agent_id=agent_id,
        agent_type_explicit=agent_type_explicit,
        routing_intent_override=routing_intent_override,
        routing_reason_override=routing_reason_override,
        support_request_signature=support_request_signature,
        workflow_routing_policy_resolution=policy_resolution,
        # The session's recorded decisions plus this request's answers: a turn that answers an
        # open workflow decision must not be held for it again.
        workflow_decisions=turn_decisions,
    )
    selected_mode = await resolve_agent_mode(db, decision.effective_agent_type)
    # Commit point of turn preparation: isolated writers later in preparation rely on the released SQLite write
    # lock.
    await db.commit()
    (
        routing_intent,
        routing_reason,
        execution_strategy,
        execution_strategy_reason,
        expected_workflow_id,
        effective_agent_type,
    ) = preserve_waiting_session_contract(
        session=session,
        agent_id=agent_id,
        agent_type_explicit=agent_type_explicit,
        routing_intent=decision.routing_intent,
        routing_reason=decision.routing_reason,
        execution_strategy=decision.execution_strategy,
        execution_strategy_reason=decision.execution_strategy_reason,
        expected_workflow_id=str(decision.workflow_id or "").strip(),
        effective_agent_type=decision.effective_agent_type,
    )
    return TurnRouting(
        policy_resolution=policy_resolution,
        strategy_decision=decision,
        routing_intent=routing_intent,
        routing_reason=routing_reason,
        effective_agent_type=effective_agent_type,
        execution_strategy=execution_strategy,
        execution_strategy_reason=execution_strategy_reason,
        expected_workflow_id=expected_workflow_id,
        selected_mode_key=selected_mode.key,
    )


def selected_workflow_contract(policy_resolution: dict[str, Any] | None) -> dict[str, Any]:
    """The configured contract of the workflow the turn selected; ``{}`` without a selection."""
    if not workflow_selection_from_resolution(policy_resolution).selected:
        return {}
    contract = (policy_resolution or {}).get("workflow_contract")
    return dict(contract) if isinstance(contract, dict) else {}


__all__ = ["TurnRouting", "resolve_turn_routing", "selected_workflow_contract"]
