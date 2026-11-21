"""Lifecycle controls for Engineering Knowledge Graph facts.

State helpers and reference matching live in sibling modules; this module keeps the lifecycle operations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorWatcherEvent, EngineeringKnowledgeGraphNode
from ...time_utils import utc_now
from .lifecycle_refs import (
    _event_reason,
    _is_delete_or_sensitive_event,
    _refs_match_filter,
    _safe_match_refs,
    extract_engineering_knowledge_event_refs,
)
from .lifecycle_state import (
    ACTIVE_LIFECYCLE_STATUSES,
    EngineeringKnowledgeLifecycleResult,
    _add_lifecycle_audit,
    _bounded_limit,
    _transition_node,
)

__all__ = [
    "cleanup_engineering_knowledge_for_deleted_source",
    "expire_engineering_knowledge",
    "invalidate_engineering_knowledge_by_refs",
    "invalidate_engineering_knowledge_for_watcher_event",
    "mark_engineering_knowledge_review_lifecycle",
    "retract_engineering_knowledge_node",
    "supersede_engineering_knowledge_node",
]


async def expire_engineering_knowledge(
    db: AsyncSession,
    *,
    actor_id: str,
    reason: str = "Validity window expired.",
    limit: int = 500,
) -> EngineeringKnowledgeLifecycleResult:
    now = utc_now()
    rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .where(
                    EngineeringKnowledgeGraphNode.status.in_(ACTIVE_LIFECYCLE_STATUSES),
                    EngineeringKnowledgeGraphNode.valid_until.is_not(None),
                    EngineeringKnowledgeGraphNode.valid_until <= now,
                )
                .order_by(EngineeringKnowledgeGraphNode.valid_until.asc())
                .limit(_bounded_limit(limit))
            )
        )
        .scalars()
        .all()
    )
    affected = []
    for node in rows:
        _transition_node(
            node,
            status="expired",
            reason=reason,
            actor_id=actor_id,
            source="expiry_policy",
            extra={"valid_until": node.valid_until.isoformat() if node.valid_until else None},
        )
        affected.append(node.id)
    _add_lifecycle_audit(
        db,
        actor_id=actor_id,
        action="engineering_knowledge.lifecycle.expired",
        resource_id="bulk",
        details={"matched_count": len(affected), "affected_node_ids": affected, "reason": reason},
    )
    await db.flush()
    return EngineeringKnowledgeLifecycleResult("expire", len(affected), tuple(affected), reason)


async def retract_engineering_knowledge_node(
    db: AsyncSession,
    node: EngineeringKnowledgeGraphNode,
    *,
    actor_id: str,
    reason: str,
    source: str = "admin_review",
    event_ref: str | None = None,
    extra: dict[str, Any] | None = None,
) -> EngineeringKnowledgeLifecycleResult:
    _transition_node(
        node,
        status="retracted",
        reason=reason,
        actor_id=actor_id,
        source=source,
        event_ref=event_ref,
        extra=extra,
    )
    _add_lifecycle_audit(
        db,
        actor_id=actor_id,
        action="engineering_knowledge.lifecycle.retracted",
        resource_id=node.id,
        details={"reason": reason, "source": source, "event_ref": event_ref},
    )
    await db.flush()
    return EngineeringKnowledgeLifecycleResult("retract", 1, (node.id,), reason)


async def supersede_engineering_knowledge_node(
    db: AsyncSession,
    node: EngineeringKnowledgeGraphNode,
    *,
    superseded_by_node_id: str,
    actor_id: str,
    reason: str,
    source: str = "admin_review",
) -> EngineeringKnowledgeLifecycleResult:
    _transition_node(
        node,
        status="stale",
        reason=reason,
        actor_id=actor_id,
        source=source,
        extra={"superseded_by_node_id": superseded_by_node_id},
    )
    _add_lifecycle_audit(
        db,
        actor_id=actor_id,
        action="engineering_knowledge.lifecycle.superseded",
        resource_id=node.id,
        details={"reason": reason, "superseded_by_node_id": superseded_by_node_id},
    )
    await db.flush()
    return EngineeringKnowledgeLifecycleResult("supersede", 1, (node.id,), reason)


async def cleanup_engineering_knowledge_for_deleted_source(
    db: AsyncSession,
    *,
    source_refs: list[str],
    actor_id: str,
    reason: str,
    source: str = "deleted_source_cleanup",
    limit: int = 500,
) -> EngineeringKnowledgeLifecycleResult:
    return await invalidate_engineering_knowledge_by_refs(
        db,
        refs=source_refs,
        actor_id=actor_id,
        reason=reason,
        event_ref=None,
        source=source,
        target_status="retracted",
        limit=limit,
        extra={"deleted_source_cleanup": True},
    )


async def invalidate_engineering_knowledge_for_watcher_event(
    db: AsyncSession,
    *,
    watcher_event: ConnectorWatcherEvent,
    actor_id: str,
    limit: int = 100,
) -> EngineeringKnowledgeLifecycleResult:
    refs = extract_engineering_knowledge_event_refs(watcher_event)
    if not refs:
        return EngineeringKnowledgeLifecycleResult("invalidate", 0, (), "No source references found on watcher event.")
    event_type = str(watcher_event.event_type or "").lower()
    target_status = "retracted" if _is_delete_or_sensitive_event(event_type) else "stale"
    reason = _event_reason(watcher_event, target_status=target_status)
    return await invalidate_engineering_knowledge_by_refs(
        db,
        refs=refs,
        actor_id=actor_id,
        reason=reason,
        event_ref=watcher_event.id,
        source="connector_watcher",
        target_status=target_status,
        limit=limit,
        extra={
            "watcher_id": watcher_event.watcher_id,
            "event_type": watcher_event.event_type,
            "external_id": watcher_event.external_id,
            "matched_refs": refs,
        },
    )


async def invalidate_engineering_knowledge_by_refs(
    db: AsyncSession,
    *,
    refs: list[str],
    actor_id: str,
    reason: str,
    event_ref: str | None,
    source: str,
    target_status: str = "stale",
    limit: int = 100,
    extra: dict[str, Any] | None = None,
) -> EngineeringKnowledgeLifecycleResult:
    safe_refs = _safe_match_refs(refs)
    if not safe_refs:
        return EngineeringKnowledgeLifecycleResult("invalidate", 0, (), "No valid source references provided.")
    status = "retracted" if target_status == "retracted" else "stale"
    rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .where(
                    EngineeringKnowledgeGraphNode.status.in_(ACTIVE_LIFECYCLE_STATUSES),
                    _refs_match_filter(safe_refs),
                )
                .order_by(EngineeringKnowledgeGraphNode.updated_at.desc())
                .limit(_bounded_limit(limit))
            )
        )
        .scalars()
        .all()
    )
    affected = []
    for node in rows:
        _transition_node(
            node,
            status=status,
            reason=reason,
            actor_id=actor_id,
            source=source,
            event_ref=event_ref,
            extra=extra,
        )
        affected.append(node.id)
    if affected:
        _add_lifecycle_audit(
            db,
            actor_id=actor_id,
            action=f"engineering_knowledge.lifecycle.{status}",
            resource_id=event_ref or "bulk",
            details={
                "matched_count": len(affected),
                "affected_node_ids": affected,
                "reason": reason,
                "source": source,
                "refs": safe_refs,
            },
        )
    await db.flush()
    return EngineeringKnowledgeLifecycleResult("invalidate", len(affected), tuple(affected), reason)


def mark_engineering_knowledge_review_lifecycle(
    node: EngineeringKnowledgeGraphNode,
    *,
    status: str,
    reason: str,
    actor_id: str,
    source: str = "admin_review",
    extra: dict[str, Any] | None = None,
) -> None:
    _transition_node(
        node,
        status=status,
        reason=reason,
        actor_id=actor_id,
        source=source,
        extra=extra,
    )
