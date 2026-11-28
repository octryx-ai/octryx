"""Routing intent of a turn: its sources, the policy override and the coding-mode promotion."""

from __future__ import annotations

from typing import Any, NamedTuple

from .agent_mode import DEFAULT_AGENT_MODE_KEY
from .workflow_routing.policy_intent import resolve_workflow_intent_from_resolution
from .workflow_routing.support_signature import (
    match_support_request_signature,
    support_request_signature_enabled,
)

ROUTING_INTENTS = frozenset(
    {"coding", "documentation", "knowledge", "admin_control", "operations", "diagnosis", "support_request"}
)
ROUTING_INTENT_LOW_CONFIDENCE_THRESHOLD = 0.78
ROUTING_INTENT_SOURCE_POLICY = "policy"
# The caller's explicit mode (UI/API ``agent_type``) decided the intent.
ROUTING_INTENT_SOURCE_EXPLICIT = "explicit"
# The explicit default: no input of the turn decided the intent (plain governed direct/diagnosis turn).
ROUTING_INTENT_SOURCE_DEFAULT = "default"
# Support-request error-signature classifier: pattern recognition on factual
# error evidence (stack traces, exceptions, timeouts) — the single allowed
# matcher in explicit routing mode, with its own switch
# ``support_request_signature_classifier`` (workflow_routing.support_signature).
ROUTING_INTENT_SOURCE_SIGNATURE = "signature"
EXPLICIT_CODING_AGENT_TYPES = frozenset({"change", "coding"})


def _coerce_routing_intent(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return (
        normalized
        if normalized
        in {"coding", "documentation", "knowledge", "admin_control", "operations", "diagnosis", "support_request"}
        else ""
    )


def _coerce_routing_intent_confidence(value: float | int | str | None) -> float:
    raw_value = value
    try:
        confidence = float(raw_value)
    except (TypeError, ValueError):
        return 0.0
    if not (confidence == confidence):
        return 0.0
    if confidence > 1:
        confidence = confidence / 100.0
    confidence = max(0.0, min(confidence, 1.0))
    return confidence


async def support_request_signature_applies(prompt: str, *, db=None) -> bool:
    # Evaluated for the current turn on every entry path, so no stored hint or earlier switch state decides. It never
    # calls a model or selects a workflow.
    text = str(prompt or "").strip()
    return bool(text) and match_support_request_signature(text) and await support_request_signature_enabled(db)


def resolve_workflow_routing_policy_intent_override(
    *,
    workflow_routing_policy_resolution: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    resolution = workflow_routing_policy_resolution if isinstance(workflow_routing_policy_resolution, dict) else {}
    if resolution.get("source") != "db" or resolution.get("status") != "matched":
        return None, None
    safety_constraints = resolution.get("safety_constraints")
    if not isinstance(safety_constraints, dict):
        return None, None
    if not isinstance(safety_constraints, dict):
        return None, None

    policy_intent, _policy_route_reason = resolve_workflow_intent_from_resolution(
        resolution=workflow_routing_policy_resolution,
    )
    if policy_intent == "coding" and bool(safety_constraints.get("diagnosis_mode")):
        return "diagnosis", "routing_policy:diagnosis_mode"
    if policy_intent and policy_intent in ROUTING_INTENTS:
        return None, None
    return None, None


def should_auto_promote_to_coding_mode(
    *,
    prompt: str,
    agent_type: str,
    agent_id: str,
    routing_intent: str | None = None,
    routing_intent_confidence: float | None = None,
    routing_intent_source: str | None = None,
) -> bool:
    # Only the policy source (matched routing or an explicit definition) may promote a turn to coding.
    text = str(prompt or "").strip()
    confidence = _coerce_routing_intent_confidence(routing_intent_confidence)
    source = str(routing_intent_source or "").strip().lower()
    if str(agent_id or "").strip() or not text:
        return False
    normalized_agent_type = str(agent_type or DEFAULT_AGENT_MODE_KEY).strip().lower()
    if normalized_agent_type not in {"", DEFAULT_AGENT_MODE_KEY, "chat"}:
        return False
    return (
        _coerce_routing_intent(routing_intent) == "coding"
        and source == ROUTING_INTENT_SOURCE_POLICY
        and confidence >= ROUTING_INTENT_LOW_CONFIDENCE_THRESHOLD
    )


class _Routing(NamedTuple):
    intent: str
    reason: str
    source: str
    confidence: float


def _routing_for_turn(
    *,
    clean_prompt: str,
    normalized_agent_type_key: str,
    agent_type_explicit: bool,
    routing_intent_override: str | None,
    routing_reason_override: str | None,
    support_request_signature: bool,
    workflow_routing_policy_resolution: dict[str, Any] | None,
) -> _Routing:
    policy_intent, policy_reason = resolve_workflow_intent_from_resolution(
        resolution=workflow_routing_policy_resolution,
        fallback_route_reason=None,
    )
    derived_override_intent, derived_override_reason = resolve_workflow_routing_policy_intent_override(
        workflow_routing_policy_resolution=workflow_routing_policy_resolution
    )
    override_intent = str(routing_intent_override or derived_override_intent or "").strip().lower()
    explicit_coding_mode = agent_type_explicit and normalized_agent_type_key in EXPLICIT_CODING_AGENT_TYPES
    # Deterministic error-signature classification (facts, not intent
    # guessing), evaluated for this turn and re-checked against its prompt.
    signature_applies = bool(support_request_signature) and match_support_request_signature(clean_prompt)

    if override_intent in ROUTING_INTENTS:
        override_reason = str(routing_reason_override or derived_override_reason or "").strip()
        routing_reason = override_reason if override_reason else f"routing_policy:{override_intent}"
        return _Routing(override_intent, routing_reason, ROUTING_INTENT_SOURCE_POLICY, 1.0)
    if policy_intent:
        return _Routing(policy_intent, policy_reason, ROUTING_INTENT_SOURCE_POLICY, 1.0)
    if explicit_coding_mode:
        return _Routing("coding", "explicit_mode:coding", ROUTING_INTENT_SOURCE_EXPLICIT, 1.0)
    if signature_applies:
        return _Routing("support_request", "intent:support_request_signature", ROUTING_INTENT_SOURCE_SIGNATURE, 1.0)
    # Explicit-first default: no explicit input of this turn decided the
    # intent, so the turn runs as a plain governed direct/diagnosis turn.
    routing_reason = "intent:diagnosis_default" if clean_prompt else "intent:empty_prompt_default"
    return _Routing("diagnosis", routing_reason, ROUTING_INTENT_SOURCE_DEFAULT, 1.0)


def _effective_agent_type(
    routing: _Routing,
    *,
    clean_prompt: str,
    normalized_agent_type: str,
    agent_id: str,
    agent_type_explicit: bool,
    explicit_target_selected: bool,
) -> tuple[str, _Routing]:
    routing_intent, routing_reason, routing_source, routing_confidence = routing
    auto_promote_to_coding = not agent_type_explicit and should_auto_promote_to_coding_mode(
        prompt=clean_prompt,
        agent_type=normalized_agent_type,
        agent_id=agent_id,
        routing_intent=routing_intent,
        routing_intent_confidence=routing_confidence,
        routing_intent_source=routing_source,
    )
    implicit_documentation_mode = (
        not explicit_target_selected
        and not agent_type_explicit
        and normalized_agent_type == DEFAULT_AGENT_MODE_KEY
        and routing_intent == "documentation"
        # Neutral start: the advisory LLM classification is display-only and
        # must not flip the effective mode/toolset; only the policy source
        # (matched definition / routing override) may.
        and routing_source == ROUTING_INTENT_SOURCE_POLICY
    )
    implicit_chat_mode = (
        not explicit_target_selected
        and not agent_type_explicit
        and normalized_agent_type == DEFAULT_AGENT_MODE_KEY
        and routing_intent == "diagnosis"
        and routing_reason in {"intent:diagnosis_default", "intent:empty_prompt_default"}
    )
    effective_agent_type = (
        "coding"
        if auto_promote_to_coding
        else "documentation"
        if implicit_documentation_mode
        else "chat"
        if implicit_chat_mode
        else normalized_agent_type
    )
    if auto_promote_to_coding:
        routing = routing._replace(intent="coding", reason="implicit_mode:coding_prompt")
    return effective_agent_type, routing
