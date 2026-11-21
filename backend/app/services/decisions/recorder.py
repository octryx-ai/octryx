"""Record gate decisions into the decision log.

``record_gate_decision`` stores one non-allow outcome of any gate; ``count_allowed`` counts an allow per hour, gate,
action and Workspace (allows are counted, never stored one by one). Both are synchronous and never raise: a
gate's decision must not fail because its record could not be kept. Records go through the policy engine's bounded
buffer (``policy_engine.decision_log``) and are written by the periodic flush (``flusher``) or the next policy
maintenance, whichever comes first; a full buffer drops the oldest record and the log says so.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from ...time_utils import utc_now
from ..observability.run_summary import in_app_run_key
from ..policy_engine.decision_log import record_decision
from ..policy_engine.schema import SCHEMA_VERSION
from ..redaction_policy import redact_secret_text
from ..request_context import get_current_request_id

logger = logging.getLogger(__name__)

GATE_CEDAR = "cedar"
GATE_TOOL_POLICY = "tool_policy"
GATE_TOOL_APPROVAL = "tool_approval"
GATE_MCP_ACCESS = "mcp_access"
GATE_EXECUTION = "execution_gate"
GATE_RUNTIME_READINESS = "runtime_readiness"
GATE_CONTENT_ROUTING = "content_routing"
GATE_CONTENT_SECURITY = "content_security"
GATE_DEVICE_JOB = "device_job"
GATE_GOVERNANCE_REVIEW = "governance_review"
GATES = (
    GATE_CEDAR, GATE_TOOL_POLICY, GATE_TOOL_APPROVAL, GATE_MCP_ACCESS, GATE_EXECUTION, GATE_RUNTIME_READINESS,
    GATE_CONTENT_ROUTING, GATE_CONTENT_SECURITY, GATE_DEVICE_JOB, GATE_GOVERNANCE_REVIEW,
)

OUTCOME_DENIED = "denied"
OUTCOME_NEEDS_APPROVAL = "needs_approval"
OUTCOME_NEEDS_CLARIFICATION = "needs_clarification"
OUTCOME_NEEDS_CONFIGURATION = "needs_configuration"
OUTCOME_APPROVED = "approved"
OUTCOME_REJECTED = "rejected"
OUTCOME_EXPIRED = "expired"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_REMEDIED = "remedied"
# A shipped content policy that reports (internal IPs): the request went on unchanged.
OUTCOME_REPORTED = "reported"
APPROVAL_OUTCOMES = (OUTCOME_APPROVED, OUTCOME_REJECTED, OUTCOME_EXPIRED, OUTCOME_CANCELLED)

MODE_ENFORCE = "enforce"
_ALLOWS: Counter[tuple[datetime, str, str, str]] = Counter()


def _hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _clip(value: Any, limit: int) -> str:
    return redact_secret_text(str(value or ""), max_chars=limit)[:limit]


def current_run_key() -> str | None:
    request_id = get_current_request_id()
    return in_app_run_key(request_id, "") if request_id else None


def build_gate_record(
    *,
    gate: str,
    outcome: str,
    action: str,
    resource: str,
    principal: str = "",
    workspace_id: str | None = None,
    session_id: str | None = None,
    run_key: str | None = None,
    rule: str | None = None,
    reason: str | None = None,
    approval_id: str | None = None,
    actor_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """The ``policy_decision_log`` row for one non-allow decision of ``gate``."""
    return {
        "id": str(uuid.uuid4()),
        "created_at": created_at or utc_now(),
        "point": gate[:40],
        "gate": gate[:40],
        "action": _clip(action, 40) or "unknown",
        "outcome": outcome[:20],
        "mode": MODE_ENFORCE,
        "workspace_id": (workspace_id or "")[:64] or None,
        "principal": _clip(principal, 200) or "unknown",
        "resource": _clip(resource, 480),
        "decision": "allow" if outcome in (OUTCOME_APPROVED, OUTCOME_REMEDIED, OUTCOME_REPORTED) else "deny",
        "legacy_decision": "none",
        "legacy_reason": None,
        "determining": [],
        "errors": [],
        "schema_version": SCHEMA_VERSION,
        "latency_us": 0,
        "session_id": session_id,
        "run_key": (run_key or current_run_key() or None),
        "rule": _clip(rule, 300) or None,
        "reason": _clip(reason, 300) or None,
        "approval_id": approval_id,
        "actor_id": actor_id,
    }


def record_gate_decision(**fields: Any) -> str | None:
    """Buffer one non-allow decision (see :func:`build_gate_record`); returns its id, ``None`` if not recorded.

    For decisions made inside a database transaction (approvals) write the row in that
    transaction instead (``build_gate_record``), so the record commits or rolls back with the decision.
    """
    try:
        entry = build_gate_record(**fields)
        record_decision(entry)
        return entry["id"]
    except Exception:  # noqa: BLE001 - recording must never change the gate's decision
        logger.warning("decision_record_failed gate=%s", fields.get("gate"), exc_info=True)
        return None


def count_allowed(*, gate: str, action: str, workspace_id: str | None = None) -> None:
    """Count one allow of ``gate`` for ``action`` in the current hour (flushed with the decision log)."""
    _ALLOWS[(_hour(utc_now()), gate[:40], str(action or "unknown")[:80], (workspace_id or "")[:64])] += 1


def take_allow_counts() -> list[tuple[datetime, str, str, str, int]]:
    """Pop the buffered allow counts (for the flush)."""
    items = [(*key, count) for key, count in _ALLOWS.items()]
    _ALLOWS.clear()
    return items


def restore_allow_counts(items: list[tuple[datetime, str, str, str, int]]) -> None:
    for hour, gate, action, workspace_id, count in items:
        _ALLOWS[(hour, gate, action, workspace_id)] += count


__all__ = [
    "APPROVAL_OUTCOMES",
    "GATES",
    "GATE_CEDAR",
    "GATE_CONTENT_ROUTING",
    "GATE_CONTENT_SECURITY",
    "GATE_DEVICE_JOB",
    "GATE_EXECUTION",
    "GATE_GOVERNANCE_REVIEW",
    "GATE_MCP_ACCESS",
    "GATE_RUNTIME_READINESS",
    "GATE_TOOL_APPROVAL",
    "GATE_TOOL_POLICY",
    "OUTCOME_APPROVED",
    "OUTCOME_CANCELLED",
    "OUTCOME_DENIED",
    "OUTCOME_EXPIRED",
    "OUTCOME_NEEDS_APPROVAL",
    "OUTCOME_NEEDS_CLARIFICATION",
    "OUTCOME_NEEDS_CONFIGURATION",
    "OUTCOME_REJECTED",
    "OUTCOME_REMEDIED",
    "OUTCOME_REPORTED",
    "build_gate_record",
    "count_allowed",
    "current_run_key",
    "record_gate_decision",
    "restore_allow_counts",
    "take_allow_counts",
]
