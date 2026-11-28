"""Execution profile and gate for an internal worker that plans and dispatches tools itself. Such a worker gets the same
envelope and gate as ``run_agent``."""

from __future__ import annotations

import logging
from typing import Any

from .execution_profile_service import build_execution_profile
from .run_capability.declared import SOURCE_WORKER_PROFILE
from .run_capability.worker_profiles import worker_run_capability
from .session.execution_gate import ExecutionGateDecision, evaluate_execution_gate

logger = logging.getLogger(__name__)

WORKER_ROUTING_INTENT = "worker"


def build_worker_execution_profile(worker_key: str, *, prompt: str) -> dict[str, Any]:
    # From its registered worker profile only.
    declared = worker_run_capability(worker_key)
    capability = {**declared.to_metadata(), "enforced": True, "worker": str(worker_key)}
    return build_execution_profile(
        prompt=prompt,
        requested_agent_type="",
        effective_agent_type=WORKER_ROUTING_INTENT,
        execution_strategy="direct",
        execution_strategy_reason=f"worker_profile:{worker_key}",
        routing_intent=WORKER_ROUTING_INTENT,
        routing_reason=f"worker_profile:{worker_key}",
        routing_intent_confidence=1.0,
        routing_intent_source=SOURCE_WORKER_PROFILE,
        workflow_id="",
        workflow_contract=None,
        capability=capability,
        governed_origin=SOURCE_WORKER_PROFILE,
    ).to_metadata()


def worker_turn_refusal(worker_key: str, *, prompt: str) -> ExecutionGateDecision | None:
    profile = build_worker_execution_profile(worker_key, prompt=prompt)
    decision = evaluate_execution_gate(profile)
    if decision.allowed:
        return None
    logger.info(
        "worker.turn.blocked_by_execution_profile",
        extra={
            "worker": str(worker_key),
            "profile_status": decision.status,
            "decision_source": decision.decision_source,
            "profile_id": profile.get("profile_id"),
        },
    )
    return decision


__all__ = ["WORKER_ROUTING_INTENT", "build_worker_execution_profile", "worker_turn_refusal"]
