"""Execution profile contract for backend routing decisions.

The execution profile is an audit-friendly envelope around the execution strategy
decision: the backend's one explicit place to record whether a turn is allowed, denied,
needs approval, needs configuration or needs clarification. The execution gate
(``services/session/execution_gate.py``) starts the loop only for an allowed profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_profile_status import EXECUTION_PROFILE_STATUS_ALLOWED, ExecutionProfileStatus, _decide_status
from .workflow_routing.workflow_selection import workflow_selection_from_resolution

EXECUTION_PROFILE_VERSION = "execution_profile.v1"

# There is no pre-turn LLM routing. The envelope carries the ``llm_router``
# key with this fixed state so readers see an explicit "no router call".
LLM_ROUTER_NOT_USED: dict[str, str] = {"status": "not_used"}


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Normalized routing/profile decision persisted on a session or trace."""

    status: ExecutionProfileStatus
    profile_id: str
    decision_source: str
    reason: str
    routing_intent: str
    routing_reason: str
    routing_intent_confidence: float
    routing_intent_source: str
    requested_agent_type: str
    effective_agent_type: str
    execution_strategy: str
    execution_strategy_reason: str
    workflow_id: str
    workflow_contract: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    # Run capability section (services/run_capability): the class the run executes
    # under, its source, and whether the request's agent_type was ignored.
    capability: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": EXECUTION_PROFILE_VERSION,
            "status": self.status,
            "profile_id": self.profile_id,
            "decision_source": self.decision_source,
            "reason": self.reason,
            "routing_intent": self.routing_intent,
            "routing_reason": self.routing_reason,
            "routing_intent_confidence": self.routing_intent_confidence,
            "routing_intent_source": self.routing_intent_source,
            "requested_agent_type": self.requested_agent_type,
            "effective_agent_type": self.effective_agent_type,
            "execution_strategy": self.execution_strategy,
            "execution_strategy_reason": self.execution_strategy_reason,
            "workflow_id": self.workflow_id or None,
            "workflow_contract": dict(self.workflow_contract or {}),
            "policy": dict(self.policy or {}),
            "runtime": dict(self.runtime or {}),
            "capability": dict(self.capability or {}),
            "llm_router": dict(LLM_ROUTER_NOT_USED),
        }


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not confidence == confidence:
        return 0.0
    if confidence > 1:
        confidence = confidence / 100.0
    return max(0.0, min(confidence, 1.0))


def _routing_policy_summary(workflow_routing_policy_resolution: dict[str, Any] | None) -> dict[str, Any]:
    resolution = workflow_routing_policy_resolution if isinstance(workflow_routing_policy_resolution, dict) else {}
    # The closed workflow selection this resolution makes: the reason a turn
    # has, or has no, workflow is recorded as a code, never inferred from the prompt.
    selection = workflow_selection_from_resolution(resolution)
    return {
        "source": resolution.get("source"),
        "status": resolution.get("status"),
        "policy_id": resolution.get("policy_id"),
        "policy_version_id": resolution.get("policy_version_id"),
        "matched_group_id": resolution.get("matched_group_id"),
        "workflow_id": resolution.get("workflow_id"),
        "workflow_class": resolution.get("workflow_class"),
        "selection_state": selection.state,
        "selection_reason_code": selection.reason_code,
    }


def _select_profile_identity(
    *,
    status: ExecutionProfileStatus,
    decision_source: str,
    routing_intent: str,
    execution_strategy: str,
    workflow_id: str,
) -> str:
    if status != EXECUTION_PROFILE_STATUS_ALLOWED:
        return f"{status}:{decision_source}"
    if workflow_id:
        return f"workflow:{workflow_id}"
    if execution_strategy == "direct" and routing_intent in {"diagnosis", "chat"}:
        return "direct_chat_safe"
    return f"{execution_strategy}:{routing_intent or 'unknown'}"

def build_execution_profile(
    *,
    prompt: str,
    requested_agent_type: str,
    effective_agent_type: str,
    execution_strategy: str,
    execution_strategy_reason: str,
    routing_intent: str,
    routing_reason: str,
    routing_intent_confidence: Any,
    routing_intent_source: str,
    workflow_id: str,
    workflow_contract: dict[str, Any] | None,
    agent_type_explicit: bool = False,
    workflow_routing_policy_resolution: dict[str, Any] | None = None,
    runtime_target_id: str | None = None,
    runtime_label: str | None = None,
    capability: dict[str, Any] | None = None,
    governed_origin: str | None = None,
) -> ExecutionProfile:
    """Build the turn's profile envelope.

    ``governed_origin`` names the declared non-chat origin that decided the run capability (a
    schedule, flow, worker profile, recorded run profile or parent run, see
    ``services/run_capability``). An allowed turn outside a matched workflow then records that
    origin as its decision source, not the routing classifier of the message text.
    """
    capability_section = dict(capability or {})
    status, decision_source, reason = _decide_status(
        prompt=prompt,
        agent_type_explicit=agent_type_explicit,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution,
        routing_intent_source=routing_intent_source,
        routing_reason=routing_reason,
        capability_section=capability_section,
        workflow_contract=workflow_contract,
        governed_origin=governed_origin,
    )
    return _assemble_profile(
        status,
        decision_source,
        reason,
        requested_agent_type=requested_agent_type,
        effective_agent_type=effective_agent_type,
        execution_strategy=execution_strategy,
        execution_strategy_reason=execution_strategy_reason,
        routing_intent=routing_intent,
        routing_reason=routing_reason,
        routing_intent_confidence=routing_intent_confidence,
        routing_intent_source=routing_intent_source,
        workflow_id=workflow_id,
        workflow_contract=workflow_contract,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution,
        runtime_target_id=runtime_target_id,
        runtime_label=runtime_label,
        capability_section=capability_section,
    )


def _assemble_profile(
    status: ExecutionProfileStatus,
    decision_source: str,
    reason: str,
    *,
    requested_agent_type: str,
    effective_agent_type: str,
    execution_strategy: str,
    execution_strategy_reason: str,
    routing_intent: str,
    routing_reason: str,
    routing_intent_confidence: Any,
    routing_intent_source: str,
    workflow_id: str,
    workflow_contract: dict[str, Any] | None,
    workflow_routing_policy_resolution: dict[str, Any] | None,
    runtime_target_id: str | None,
    runtime_label: str | None,
    capability_section: dict[str, Any],
) -> ExecutionProfile:
    clean_workflow_id = str(workflow_id or "").strip()
    clean_routing_intent = str(routing_intent or "").strip() or "diagnosis"
    clean_execution_strategy = str(execution_strategy or "").strip() or "direct"
    profile_id = _select_profile_identity(
        status=status,
        decision_source=decision_source,
        routing_intent=clean_routing_intent,
        execution_strategy=clean_execution_strategy,
        workflow_id=clean_workflow_id,
    )
    return ExecutionProfile(
        status=status,
        profile_id=profile_id,
        decision_source=decision_source,
        reason=reason,
        routing_intent=clean_routing_intent,
        routing_reason=str(routing_reason or "").strip(),
        routing_intent_confidence=_coerce_confidence(routing_intent_confidence),
        routing_intent_source=str(routing_intent_source or "").strip(),
        requested_agent_type=str(requested_agent_type or "").strip(),
        effective_agent_type=str(effective_agent_type or "").strip(),
        execution_strategy=clean_execution_strategy,
        execution_strategy_reason=str(execution_strategy_reason or "").strip(),
        workflow_id=clean_workflow_id,
        workflow_contract=dict(workflow_contract or {}),
        policy=_routing_policy_summary(workflow_routing_policy_resolution),
        runtime={
            "runtime_target_id": str(runtime_target_id or "").strip() or None,
            "runtime_label": str(runtime_label or "").strip() or None,
        },
        capability=capability_section,
    )

__all__ = [
    "EXECUTION_PROFILE_VERSION",
    "LLM_ROUTER_NOT_USED",
    "ExecutionProfile",
    "build_execution_profile",
]
