"""Bounded, redacted trace projection of a persisted execution profile."""

from __future__ import annotations

# Trace projection: every turn trace records which profile was
# in effect. Whitelisted scalar fields only: the envelope also carries the
# workflow contract and requirement tool lists, which do not belong in trace
# metadata, and text is bounded so metadata-only capture stays compact.
TRACE_EXECUTION_PROFILE_KEY = "execution_profile"
_TRACE_PROFILE_FIELDS = (
    "version",
    "status",
    "profile_id",
    "decision_source",
    "reason",
    "routing_intent",
    "routing_intent_source",
    "routing_intent_confidence",
    "execution_strategy",
    "requested_agent_type",
    "effective_agent_type",
    "workflow_id",
)
_TRACE_NESTED_FIELDS = {
    "policy": (
        "source",
        "status",
        "policy_id",
        "policy_version_id",
        "matched_group_id",
        "workflow_id",
        "workflow_class",
        "selection_state",
        "selection_reason_code",
    ),
    "runtime": ("runtime_target_id", "runtime_label"),
    "requirements": ("status", "satisfied"),
    "capability": (
        "class",
        "source",
        "enforced",
        "requested_agent_type",
        "agent_type_ignored",
        "escalation_decision",
        "escalated",
        "parent_class",
        "capped_by_parent",
        "agent_ceiling",
        "capped_by_agent",
    ),
}
_TRACE_TEXT_MAX_CHARS = 300


