"""Status, decision source and reason of a turn's execution profile."""

from __future__ import annotations

from typing import Any, Literal

from .execution_strategy_intent import ROUTING_INTENT_SOURCE_EXPLICIT, ROUTING_INTENT_SOURCE_SIGNATURE
from .project_activity import PROJECT_INACTIVE
from .run_admission.denials import WORKFLOW_ARCHIVED
from .run_capability.declared import SOURCE_WORKER_PROFILE
from .workflow_contracts.variant import WORKFLOW_VARIANT_DECISION_SOURCE, unresolved_workflow_variant

ExecutionProfileStatus = Literal[
    "allowed",
    "denied",
    "needs_approval",
    "needs_configuration",
    "needs_clarification",
]

EXECUTION_PROFILE_STATUS_ALLOWED: ExecutionProfileStatus = "allowed"
EXECUTION_PROFILE_STATUS_DENIED: ExecutionProfileStatus = "denied"
EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL: ExecutionProfileStatus = "needs_approval"
EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION: ExecutionProfileStatus = "needs_configuration"
EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION: ExecutionProfileStatus = "needs_clarification"

# The explicit decision of each remaining routing source: the caller's explicit mode (also when it reaches the
# profile only as the routing source), the support-request error signature and a registered worker profile.
_ROUTING_SOURCE_DECISIONS = {
    ROUTING_INTENT_SOURCE_EXPLICIT: ("explicit_ui_context", "User or caller selected an explicit mode."),
    ROUTING_INTENT_SOURCE_SIGNATURE: (
        "support_request_signature", "The support-request error signature selected the routing intent."),
    SOURCE_WORKER_PROFILE: ("worker_profile", "The registered worker profile decides this turn."),
}

# Decision sources of a matched workflow: a governed origin never replaces them.
_WORKFLOW_DECISION_SOURCES = frozenset({"explicit_workflow_key", "workflow_run"})


def _derive_profile_status_and_source(
    *,
    prompt: str,
    agent_type_explicit: bool,
    workflow_routing_policy_resolution: dict[str, Any] | None,
    routing_intent_source: str,
    routing_reason: str,
) -> tuple[ExecutionProfileStatus, str, str]:
    text = str(prompt or "").strip()
    if not text:
        return EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION, "input", "Prompt is empty."

    resolution = workflow_routing_policy_resolution if isinstance(workflow_routing_policy_resolution, dict) else {}
    decided = _resolution_status_and_source(resolution)
    if decided is not None:
        return decided

    if agent_type_explicit:
        return EXECUTION_PROFILE_STATUS_ALLOWED, "explicit_ui_context", "User or caller selected an explicit mode."

    if str(routing_intent_source or "").strip() == "policy":
        return EXECUTION_PROFILE_STATUS_ALLOWED, "policy", "Policy selected the routing intent."

    if routing_reason in {"intent:diagnosis_default", "intent:empty_prompt_default"}:
        return EXECUTION_PROFILE_STATUS_ALLOWED, "direct_chat_safe", "No workflow matched; using safe direct chat."

    named = _ROUTING_SOURCE_DECISIONS.get(str(routing_intent_source or "").strip())
    if named is not None:
        return EXECUTION_PROFILE_STATUS_ALLOWED, *named
    # Every routing source is named above; an unnamed one never runs on a guess.
    return (
        EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
        "routing_source_unknown",
        f"No routing decision source explains this turn ({str(routing_intent_source or '').strip() or 'none'}).",
    )



def _resolution_status_and_source(resolution: dict[str, Any]) -> tuple[ExecutionProfileStatus, str, str] | None:
    if resolution.get("status") == PROJECT_INACTIVE:
        return EXECUTION_PROFILE_STATUS_DENIED, PROJECT_INACTIVE, str(resolution.get("unmatched_reason") or "")
    if resolution.get("status") == WORKFLOW_ARCHIVED:  # an archived workflow is a typed denial
        return EXECUTION_PROFILE_STATUS_DENIED, WORKFLOW_ARCHIVED, str(resolution.get("unmatched_reason") or "")
    if resolution.get("status") == "workflow_run_required":  # a phased workflow is a run
        return (EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION, "workflow_run_required",
                str(resolution.get("unmatched_reason") or ""))
    if resolution.get("source") == "explicit_workflow_key" and resolution.get("status") == "unknown_key":
        return (
            EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
            "explicit_workflow_key",
            str(
                resolution.get("unmatched_reason")
                or "The requested workflow_key does not resolve to a published workflow."
            ),
        )
    if resolution.get("source") == "workflow_run" and resolution.get("status") == "held":
        # The session follows a workflow run that waits, is paused or cannot run: nothing runs.
        return (
            str(resolution.get("profile_status") or EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION),
            "workflow_run",
            str(resolution.get("unmatched_reason") or "The workflow run holds this turn."),
        )
    if (resolution.get("source") == "db" and resolution.get("status") == "matched"
            and resolution.get("selection_source") == "workflow_run"):
        return EXECUTION_PROFILE_STATUS_ALLOWED, "workflow_run", "The workflow run's current phase governs this turn."

    return None


def _decide_status(
    *,
    prompt: str,
    agent_type_explicit: bool,
    workflow_routing_policy_resolution: dict[str, Any] | None,
    routing_intent_source: str,
    routing_reason: str,
    capability_section: dict[str, Any],
    workflow_contract: dict[str, Any] | None,
    governed_origin: str | None,
) -> tuple[ExecutionProfileStatus, str, str]:
    status, decision_source, reason = _derive_profile_status_and_source(
        prompt=prompt,
        agent_type_explicit=agent_type_explicit,
        workflow_routing_policy_resolution=workflow_routing_policy_resolution,
        routing_intent_source=routing_intent_source,
        routing_reason=routing_reason,
    )
    if status == EXECUTION_PROFILE_STATUS_ALLOWED and capability_section.get("status") == (
        EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    ):
        # A selected workflow without a valid capability class cannot run.
        status, decision_source = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION, "run_capability"
        reason = str(capability_section.get("reason") or "The workflow declares no valid capability class.")
    unresolved_variant = unresolved_workflow_variant(workflow_contract)
    if status == EXECUTION_PROFILE_STATUS_ALLOWED and unresolved_variant is not None:
        # The selected definition does not fix its variant consistently; nothing is guessed.
        status, decision_source = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION, WORKFLOW_VARIANT_DECISION_SOURCE
        reason = (
            f"The selected workflow definition does not configure its {unresolved_variant.get('family') or 'workflow'} "
            f"variant consistently ({unresolved_variant.get('reason_code') or 'unknown'})."
        )
    origin = str(governed_origin or "").strip()
    if origin and status == EXECUTION_PROFILE_STATUS_ALLOWED and decision_source not in _WORKFLOW_DECISION_SOURCES:
        decision_source, reason = origin, f"The run's declared origin '{origin}' governs this turn."
    return status, decision_source, reason
