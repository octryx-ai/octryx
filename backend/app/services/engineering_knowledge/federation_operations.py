"""Operational controls and audit helpers for Engineering Knowledge federation."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AuditLog,
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeFederationSyncRun,
    EngineeringKnowledgeGraphNode,
    User,
)
from ...time_utils import utc_now
from .federation_serializers import serialize_federation_feed, serialize_federation_sync_run

FEDERATION_USAGE_ACTION = "engineering_knowledge_federation.usage"


async def add_federation_audit_event(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
    current_user: User,
) -> AuditLog:
    event = AuditLog(
        user_id=current_user.id,
        action=f"engineering_knowledge_federation.{action}",
        resource_type=resource_type,
        resource_id=resource_id,
        details=_safe_audit_details(details),
    )
    db.add(event)
    await db.flush()
    return event


async def disable_engineering_knowledge_federation_feed(
    db: AsyncSession,
    *,
    feed_id: str,
    reason: str,
    current_user: User,
) -> dict[str, Any]:
    feed = await db.get(EngineeringKnowledgeFederationFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge federation feed not found")
    feed.status = "disabled"
    feed.last_sync_status = "disabled"
    feed.last_error = str(reason or "Emergency disabled by admin").strip()[:2000]
    feed.last_sync_at = utc_now()
    run = EngineeringKnowledgeFederationSyncRun(
        feed_id=feed.id,
        operation="emergency_disable",
        status="success",
        result={"reason": feed.last_error, "required_action": "manual_admin_reenable"},
        completed_at=utc_now(),
        created_by_user_id=current_user.id,
    )
    db.add(run)
    await add_federation_audit_event(
        db,
        action="feed_emergency_disabled",
        resource_type="engineering_knowledge_federation_feed",
        resource_id=feed.id,
        details={"reason": feed.last_error, "publisher_instance_id": feed.publisher_instance_id},
        current_user=current_user,
    )
    await db.flush()
    return {"feed": serialize_federation_feed(feed), "sync_run": serialize_federation_sync_run(run)}


async def propagate_federation_retractions_to_graph(
    db: AsyncSession,
    *,
    publisher_instance_id: str,
    package_ids: set[str],
    current_user: User,
) -> dict[str, Any]:
    if not package_ids:
        return {"affected_fact_ids": [], "required_action": "none"}
    affected: list[EngineeringKnowledgeGraphNode] = []
    rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode).where(
                    EngineeringKnowledgeGraphNode.node_key.like(f"federated:{publisher_instance_id}:%"),
                    EngineeringKnowledgeGraphNode.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    for node in rows:
        federation = dict((node.properties_json or {}).get("federation") or {})
        if federation.get("publisher_instance_id") != publisher_instance_id:
            continue
        if str(federation.get("package_id") or "") not in package_ids:
            continue
        node.status = "retracted"
        federation["import_status"] = "retracted"
        properties = dict(node.properties_json or {})
        properties["federation"] = federation
        properties["lifecycle"] = {
            "state": "retracted",
            "reason": "Federated package retraction received",
            "source": "federation_retraction",
            "changed_at": utc_now().isoformat(),
        }
        node.properties_json = properties
        affected.append(node)
    if affected:
        await add_federation_audit_event(
            db,
            action="retraction_propagated",
            resource_type="engineering_knowledge_graph",
            resource_id=",".join(sorted(package_ids)),
            details={
                "publisher_instance_id": publisher_instance_id,
                "package_ids": sorted(package_ids),
                "affected_fact_ids": [node.id for node in affected],
                "required_action": "review_retracted_imported_facts",
            },
            current_user=current_user,
        )
    await db.flush()
    return {
        "affected_fact_ids": [node.id for node in affected],
        "required_action": "review_retracted_imported_facts" if affected else "none",
    }


async def record_federated_knowledge_usage(
    db: AsyncSession,
    *,
    package_record_id: str | None,
    package_id: str,
    run_id: str,
    session_id: str | None,
    fact_ids: list[str],
    current_user: User,
) -> dict[str, Any]:
    safe_package_id = str(package_id or "").strip()
    safe_run_id = str(run_id or "").strip()
    if not safe_package_id:
        raise HTTPException(status_code=400, detail="package_id is required")
    if not safe_run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    details = {
        "package_record_id": package_record_id,
        "package_id": safe_package_id,
        "run_id": safe_run_id,
        "session_id": session_id,
        "fact_ids": [str(item) for item in fact_ids if str(item or "").strip()][:50],
    }
    event = await add_federation_audit_event(
        db,
        action="usage",
        resource_type="engineering_knowledge_federation_package",
        resource_id=package_record_id or package_id,
        details=details,
        current_user=current_user,
    )
    return _serialize_usage_event(event)


async def get_federation_usage_impact(
    db: AsyncSession,
    *,
    package_id: str | None = None,
    package_record_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.action == FEDERATION_USAGE_ACTION)
                .order_by(AuditLog.created_at.desc())
                .limit(safe_limit * 4)
            )
        )
        .scalars()
        .all()
    )
    events = []
    for event in rows:
        details = dict(event.details or {})
        if package_id and details.get("package_id") != package_id:
            continue
        if package_record_id and details.get("package_record_id") != package_record_id:
            continue
        events.append(_serialize_usage_event(event))
        if len(events) >= safe_limit:
            break
    return {"count": len(events), "usage_events": events}


async def federation_operational_summary(db: AsyncSession) -> dict[str, Any]:
    runs = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationSyncRun).order_by(
                    EngineeringKnowledgeFederationSyncRun.started_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    failed_imports = [
        run for run in runs if run.status == "failed" and run.operation in {"import", "poll", "retraction_sync"}
    ]
    signature_failures = [
        run for run in runs if any(str(error.get("code") or "") == "invalid_signature" for error in run.errors or [])
    ]
    policy_blocked = [
        run
        for run in runs
        if any(str(error.get("code") or "").startswith("blocked") for error in run.errors or [])
    ]
    usage = await get_federation_usage_impact(db, limit=20)
    return {
        "failed_import_count": len(failed_imports),
        "signature_failure_count": len(signature_failures),
        "policy_blocked_count": len(policy_blocked),
        "usage_events": usage["usage_events"],
    }


def _safe_audit_details(details: dict[str, Any]) -> dict[str, Any]:
    return _redact_sensitive_value(details)


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            safe[text_key] = "[REDACTED]" if _is_sensitive_key(text_key) else _redact_sensitive_value(item)
        return safe
    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in ("password", "secret", "token", "private_key", "raw_payload"))


def _serialize_usage_event(event: AuditLog) -> dict[str, Any]:
    details = dict(event.details or {})
    return {
        "id": event.id,
        "run_id": details.get("run_id"),
        "session_id": details.get("session_id"),
        "package_id": details.get("package_id"),
        "package_record_id": details.get("package_record_id"),
        "fact_ids": list(details.get("fact_ids") or []),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


__all__ = [
    "add_federation_audit_event",
    "disable_engineering_knowledge_federation_feed",
    "federation_operational_summary",
    "get_federation_usage_impact",
    "propagate_federation_retractions_to_graph",
    "record_federated_knowledge_usage",
]
