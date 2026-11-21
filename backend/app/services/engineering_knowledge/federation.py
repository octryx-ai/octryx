"""Publish/subscribe state for signed Engineering Knowledge packages."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgeFederationFeed,
    User,
)
from .federation_import_steps import (
    _audit_import,
    _import_dry_run,
    _import_operation,
    _import_status,
    _record_import_run,
)
from .federation_inputs import _enum, _optional_text, _required_text, _safe_dict
from .federation_operations import add_federation_audit_event
from .federation_package import validate_engineering_knowledge_package_payload
from .federation_records import (
    _apply_retractions,
    _create_sync_run,
    _get_optional_feed,
    _require_feed,
    _require_package_signature,
    _update_feed_sync_state,
    _upsert_package_record,
)
from .federation_serializers import (
    serialize_federation_feed,
    serialize_federation_package,
    serialize_federation_sync_run,
)

FEED_TYPES = {"publisher", "subscriber"}
SYNC_MODES = {"manual", "polling", "webhook"}
FEED_STATUSES = {"active", "paused", "disabled"}


async def create_engineering_knowledge_federation_feed(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    name = _required_text(payload.get("name"), "name", max_len=220)
    existing = (
        await db.execute(
            select(EngineeringKnowledgeFederationFeed).where(EngineeringKnowledgeFederationFeed.name == name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Federation feed name already exists")
    feed_type = _enum(payload.get("feed_type") or "subscriber", FEED_TYPES, "feed_type")
    sync_mode = _enum(payload.get("sync_mode") or "manual", SYNC_MODES, "sync_mode")
    status = _enum(payload.get("status") or "active", FEED_STATUSES, "status")
    feed = EngineeringKnowledgeFederationFeed(
        name=name,
        feed_type=feed_type,
        publisher_instance_id=_required_text(payload.get("publisher_instance_id"), "publisher_instance_id"),
        endpoint_url=_optional_text(payload.get("endpoint_url"), max_len=2000),
        sync_mode=sync_mode,
        status=status,
        publisher_trust_policy=_safe_dict(payload.get("publisher_trust_policy")),
        subscriber_policy=_safe_dict(payload.get("subscriber_policy")),
        package_filter=_safe_dict(payload.get("package_filter")),
        signing_key_ref=_optional_text(payload.get("signing_key_ref"), max_len=240),
        verification_key_ref=_optional_text(payload.get("verification_key_ref"), max_len=240),
        created_by_user_id=current_user.id,
    )
    db.add(feed)
    await db.flush()
    await add_federation_audit_event(
        db,
        action="feed_subscribed" if feed.feed_type == "subscriber" else "feed_publisher_created",
        resource_type="engineering_knowledge_federation_feed",
        resource_id=feed.id,
        details={
            "feed_type": feed.feed_type,
            "publisher_instance_id": feed.publisher_instance_id,
            "sync_mode": feed.sync_mode,
            "status": feed.status,
        },
        current_user=current_user,
    )
    return serialize_federation_feed(feed)


async def publish_signed_engineering_knowledge_package(
    db: AsyncSession,
    *,
    package: dict[str, Any],
    current_user: User,
    feed_id: str | None = None,
) -> dict[str, Any]:
    validate_engineering_knowledge_package_payload(package)
    _require_package_signature(package)
    feed = await _get_optional_feed(db, feed_id)
    record, action = await _upsert_package_record(
        db,
        package=package,
        direction="published",
        feed=feed,
        current_user=current_user,
        dry_run_result={"status": "not_required", "publish_only": True},
    )
    run = await _create_sync_run(
        db,
        feed=feed,
        package_record=record,
        operation="publish" if action == "created" else action,
        status="success",
        result={"action": action, "package_record_id": record.id},
        current_user=current_user,
    )
    await _update_feed_sync_state(feed, status="success", error=None)
    await add_federation_audit_event(
        db,
        action="package_published",
        resource_type="engineering_knowledge_federation_package",
        resource_id=record.id,
        details={"action": action, "package_id": record.package_id, "feed_id": feed.id if feed else None},
        current_user=current_user,
    )
    return {
        "action": action,
        "package": serialize_federation_package(record),
        "sync_run": serialize_federation_sync_run(run),
    }


async def import_signed_engineering_knowledge_package(
    db: AsyncSession,
    *,
    feed_id: str,
    package: dict[str, Any],
    current_user: User,
    verification_key: str | None = None,
) -> dict[str, Any]:
    feed = await _require_feed(db, feed_id)
    if feed.status == "disabled":
        raise HTTPException(status_code=409, detail="Engineering Knowledge federation feed is disabled")
    _require_package_signature(package)
    dry_run = await _import_dry_run(db, package, verification_key=verification_key)
    status = _import_status(package, dry_run)
    record, action = await _upsert_package_record(
        db,
        package=package,
        direction="imported",
        feed=feed,
        current_user=current_user,
        dry_run_result=dry_run,
        status=status,
        review_status="pending_review" if status == "pending_review" else "not_required",
    )
    retraction_result = await _apply_retractions(
        db,
        package=package,
        publisher_instance_id=record.publisher_instance_id,
        current_user=current_user,
    )
    operation = _import_operation(retraction_result, action)
    run_status = "failed" if dry_run["status"] == "blocked" else "success"
    run = await _record_import_run(
        db,
        feed=feed,
        record=record,
        operation=operation,
        run_status=run_status,
        result={"action": action, "dry_run": dry_run, "retractions": retraction_result},
        dry_run=dry_run,
        current_user=current_user,
    )
    await _audit_import(
        db,
        record=record,
        feed=feed,
        operation=operation,
        run_status=run_status,
        dry_run=dry_run,
        current_user=current_user,
    )
    return {
        "action": action,
        "package": serialize_federation_package(record),
        "sync_run": serialize_federation_sync_run(run),
        "dry_run": dry_run,
        "retractions": retraction_result,
    }


async def record_engineering_knowledge_federation_sync_failure(
    db: AsyncSession,
    *,
    feed_id: str,
    error: str,
    current_user: User,
    operation: str = "poll",
) -> dict[str, Any]:
    feed = await _require_feed(db, feed_id)
    message = _required_text(error, "error", max_len=2000)
    run = await _create_sync_run(
        db,
        feed=feed,
        package_record=None,
        operation=operation,
        status="failed",
        result={},
        errors=[{"code": "sync_failed", "message": message}],
        current_user=current_user,
    )
    await _update_feed_sync_state(feed, status="failed", error=message)
    await add_federation_audit_event(
        db,
        action="sync_failed",
        resource_type="engineering_knowledge_federation_feed",
        resource_id=feed.id,
        details={"operation": operation, "error": message},
        current_user=current_user,
    )
    return {"sync_run": serialize_federation_sync_run(run), "feed": serialize_federation_feed(feed)}


__all__ = [
    "create_engineering_knowledge_federation_feed",
    "import_signed_engineering_knowledge_package",
    "publish_signed_engineering_knowledge_package",
    "record_engineering_knowledge_federation_sync_failure",
]
