"""Bounded, redacted trace projection of a persisted execution profile."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .redaction_policy import redact_secret_payload

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


def _trace_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, float) and not math.isfinite(value):
        # NaN/inf are not valid JSON (PostgreSQL JSONB rejects them).
        return None
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text[:_TRACE_TEXT_MAX_CHARS] if text else None
    return None


def _trace_fields(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    projected: dict[str, Any] = {}
    for name in fields:
        value = _trace_scalar(source.get(name))
        if value is not None:
            projected[name] = value
    return projected


def execution_profile_trace_summary(profile: Any) -> dict[str, Any] | None:
    """Return the bounded, redacted trace projection of a persisted profile, or None.

    Redacted here as well as by the trace layer: the turn trace stores its
    context snapshot without a redaction pass.
    """
    if not isinstance(profile, Mapping) or not str(profile.get("status") or "").strip():
        return None
    summary = _trace_fields(profile, _TRACE_PROFILE_FIELDS)
    for key, fields in _TRACE_NESTED_FIELDS.items():
        nested = _trace_fields(profile.get(key), fields)
        if nested:
            summary[key] = nested
    return redact_secret_payload(summary)
