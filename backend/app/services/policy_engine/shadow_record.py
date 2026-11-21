"""The decision-log record of one shadow comparison (``shadow.shadow_decision`` stores non-matches)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...time_utils import utc_now
from ..redaction_policy import redact_secret_text
from .schema import SCHEMA_VERSION

if TYPE_CHECKING:
    from .points import PointQuery
    from .runtime import PolicyRuntime
    from .shadow import LegacyDecision, PolicyComparison

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"


def _decision(allowed: bool | None) -> str:
    return DECISION_ALLOW if allowed else DECISION_DENY


def _entry(query: PointQuery, legacy: LegacyDecision, comparison: PolicyComparison, runtime: PolicyRuntime,
           digest: str | None) -> dict[str, Any]:
    return {
        "id": comparison.record_id,
        "created_at": utc_now(),
        "point": query.point,
        "action": query.action,
        "outcome": comparison.outcome,
        "mode": runtime.mode,
        "workspace_id": query.workspace_id[:64],
        "principal": query.principal.label()[:200],
        "resource": redact_secret_text(query.log_resource or query.resource, max_chars=480),
        "decision": _decision(comparison.cedar_allowed),
        "legacy_decision": _decision(legacy.allowed),
        "legacy_reason": str(legacy.reason or "")[:160] or None,
        "determining": list(comparison.determining)[:50],
        "errors": list(comparison.errors)[:20],
        "policy_set_digest": digest,
        "custom_version": runtime.custom_version,
        "schema_version": SCHEMA_VERSION,
        "latency_us": comparison.latency_us,
        "content": dict(query.log_content) if query.log_content is not None else None,
    }


__all__ = ["DECISION_ALLOW", "DECISION_DENY"]
