"""Package records, sync runs and feed lookups behind knowledge federation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeFederationPackage,
    EngineeringKnowledgeFederationSyncRun,
    User,
)
from ...time_utils import utc_now
from .federation_operations import propagate_federation_retractions_to_graph


async def _upsert_package_record(
    db: AsyncSession,
    *,
    package: dict[str, Any],
    direction: str,
    feed: EngineeringKnowledgeFederationFeed | None,
    current_user: User,
    dry_run_result: dict[str, Any],
    status: str | None = None,
    review_status: str | None = None,
) -> tuple[EngineeringKnowledgeFederationPackage, str]:
    checksum = _package_checksum(package)
    publisher = str(dict(package.get("publisher") or {}).get("instance_id") or "").strip()
    package_id = str(package.get("package_id") or "").strip()
    existing_same_checksum = await _find_package_record(db, direction, publisher, package_id, checksum)
    if existing_same_checksum is not None:
        return existing_same_checksum, "duplicate"
    version = await _next_package_version(db, direction=direction, publisher=publisher, package_id=package_id)
    record = EngineeringKnowledgeFederationPackage(
        feed_id=feed.id if feed else None,
        direction=direction,
        package_id=package_id,
        publisher_instance_id=publisher,
        schema_version=str(package.get("schema_version") or ""),
        package_checksum=checksum,
        signature=dict(package.get("signature") or {}),
        content_json=package,
        classification=str(package.get("classification") or "internal"),
        trust_level=str(package.get("trust_level") or "gold"),
        status=status or ("published" if direction == "published" else "pending_review"),
        review_status=review_status or ("not_required" if direction == "published" else "pending_review"),
        version=version,
        dry_run_result=dry_run_result,
        conflicts=list(dry_run_result.get("conflicts") or []),
        retraction_refs=list(package.get("retractions") or []),
        created_by_user_id=current_user.id,
    )
    db.add(record)
    await db.flush()
    return record, "created" if version == 1 else "updated"


async def _apply_retractions(
    db: AsyncSession,
    *,
    package: dict[str, Any],
    publisher_instance_id: str,
    current_user: User,
) -> dict[str, Any]:
    retractions = [item for item in package.get("retractions") or [] if isinstance(item, dict)]
    if not retractions:
        return {"retracted_count": 0, "retracted_package_ids": []}
    target_ids = {
        str(item.get("package_id") or item.get("retracts_package_id") or "").strip()
        for item in retractions
        if str(item.get("package_id") or item.get("retracts_package_id") or "").strip()
    }
    if not target_ids:
        return {"retracted_count": 0, "retracted_package_ids": []}
    rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationPackage).where(
                    EngineeringKnowledgeFederationPackage.publisher_instance_id == publisher_instance_id,
                    EngineeringKnowledgeFederationPackage.package_id.in_(target_ids),
                    EngineeringKnowledgeFederationPackage.status != "retracted",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "retracted"
        row.review_status = "retracted"
    graph_result = await propagate_federation_retractions_to_graph(
        db,
        publisher_instance_id=publisher_instance_id,
        package_ids=target_ids,
        current_user=current_user,
    )
    return {
        "retracted_count": len(rows),
        "retracted_package_ids": sorted(target_ids),
        **graph_result,
    }


async def _create_sync_run(
    db: AsyncSession,
    *,
    feed: EngineeringKnowledgeFederationFeed | None,
    package_record: EngineeringKnowledgeFederationPackage | None,
    operation: str,
    status: str,
    result: dict[str, Any],
    current_user: User,
    errors: list[dict[str, Any]] | None = None,
) -> EngineeringKnowledgeFederationSyncRun:
    run = EngineeringKnowledgeFederationSyncRun(
        feed_id=feed.id if feed else None,
        package_record_id=package_record.id if package_record else None,
        operation=operation,
        status=status,
        package_id=package_record.package_id if package_record else None,
        package_checksum=package_record.package_checksum if package_record else None,
        result=result,
        errors=list(errors or []),
        completed_at=utc_now(),
        created_by_user_id=current_user.id,
    )
    db.add(run)
    await db.flush()
    return run


async def _update_feed_sync_state(
    feed: EngineeringKnowledgeFederationFeed | None,
    *,
    status: str,
    error: str | None,
) -> None:
    if feed is None:
        return
    feed.last_sync_at = utc_now()
    feed.last_sync_status = status
    feed.last_error = error or None


async def _find_package_record(
    db: AsyncSession,
    direction: str,
    publisher: str,
    package_id: str,
    checksum: str,
) -> EngineeringKnowledgeFederationPackage | None:
    return (
        await db.execute(
            select(EngineeringKnowledgeFederationPackage).where(
                EngineeringKnowledgeFederationPackage.direction == direction,
                EngineeringKnowledgeFederationPackage.publisher_instance_id == publisher,
                EngineeringKnowledgeFederationPackage.package_id == package_id,
                EngineeringKnowledgeFederationPackage.package_checksum == checksum,
            )
        )
    ).scalar_one_or_none()


async def _next_package_version(db: AsyncSession, *, direction: str, publisher: str, package_id: str) -> int:
    current = (
        await db.execute(
            select(func.max(EngineeringKnowledgeFederationPackage.version)).where(
                EngineeringKnowledgeFederationPackage.direction == direction,
                EngineeringKnowledgeFederationPackage.publisher_instance_id == publisher,
                EngineeringKnowledgeFederationPackage.package_id == package_id,
            )
        )
    ).scalar_one_or_none()
    return int(current or 0) + 1


async def _get_optional_feed(db: AsyncSession, feed_id: str | None) -> EngineeringKnowledgeFederationFeed | None:
    if not feed_id:
        return None
    return await _require_feed(db, feed_id)


async def _require_feed(db: AsyncSession, feed_id: str) -> EngineeringKnowledgeFederationFeed:
    feed = await db.get(EngineeringKnowledgeFederationFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge federation feed not found")
    return feed


def _package_checksum(package: dict[str, Any]) -> str:
    encoded = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_package_signature(package: dict[str, Any]) -> None:
    signature = package.get("signature")
    if not isinstance(signature, dict) or not str(signature.get("value") or "").strip():
        raise HTTPException(status_code=400, detail="Signed Engineering Knowledge package is required")

