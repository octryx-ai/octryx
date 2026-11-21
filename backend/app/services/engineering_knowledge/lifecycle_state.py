"""Shared state, result type and audit helpers for Engineering Knowledge lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, EngineeringKnowledgeGraphNode
from ...time_utils import utc_now

ACTIVE_LIFECYCLE_STATUSES = {"active", "draft"}
TERMINAL_LIFECYCLE_STATUSES = {"expired", "rejected", "retracted", "stale"}
MAX_MATCH_REFS = 12
MAX_LIFECYCLE_HISTORY = 25


@dataclass(frozen=True)
class EngineeringKnowledgeLifecycleResult:
    """Compact result for lifecycle operations."""

    action: str
    matched_count: int
    affected_node_ids: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "matched_count": self.matched_count,
            "affected_node_ids": list(self.affected_node_ids),
            "reason": self.reason,
        }


def _transition_node(
    node: EngineeringKnowledgeGraphNode,
    *,
    status: str,
    reason: str,
    actor_id: str,
    source: str,
    event_ref: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    now = utc_now()
    properties = dict(node.properties_json or {})
    lifecycle = {
        "state": status,
        "reason": str(reason or "").strip()[:2000],
        "source": source,
        "actor_id": actor_id,
        "event_ref": event_ref,
        "changed_at": now.isoformat(),
        **{key: value for key, value in (extra or {}).items() if value not in (None, "", [])},
    }
    history = list(properties.get("lifecycle_history") or [])
    history.append(lifecycle)
    properties["lifecycle"] = lifecycle
    properties["lifecycle_history"] = history[-MAX_LIFECYCLE_HISTORY:]
    node.properties_json = properties
    node.status = status
    if status == "expired" and node.valid_until is None:
        node.valid_until = now


def _add_lifecycle_audit(
    db: AsyncSession,
    *,
    actor_id: str,
    action: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=actor_id,
            action=action,
            resource_type="engineering_knowledge_graph",
            resource_id=resource_id,
            details=details,
        )
    )


def _bounded_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    return max(1, min(parsed, 1000))
