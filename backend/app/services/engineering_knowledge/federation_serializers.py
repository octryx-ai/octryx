"""Serialization helpers for Engineering Knowledge federation records."""

from __future__ import annotations

from typing import Any

from ...models import (
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeFederationPackage,
    EngineeringKnowledgeFederationSyncRun,
)


def serialize_federation_feed(feed: EngineeringKnowledgeFederationFeed) -> dict[str, Any]:
    return {
        "id": feed.id,
        "name": feed.name,
        "feed_type": feed.feed_type,
        "publisher_instance_id": feed.publisher_instance_id,
        "endpoint_url": feed.endpoint_url,
        "sync_mode": feed.sync_mode,
        "status": feed.status,
        "publisher_trust_policy": dict(feed.publisher_trust_policy or {}),
        "subscriber_policy": dict(feed.subscriber_policy or {}),
        "package_filter": dict(feed.package_filter or {}),
        "signing_key_ref": feed.signing_key_ref,
        "verification_key_ref": feed.verification_key_ref,
        "last_sync_at": _iso(feed.last_sync_at),
        "last_sync_status": feed.last_sync_status,
        "last_error": feed.last_error,
        "created_by_user_id": feed.created_by_user_id,
        "created_at": _iso(feed.created_at),
        "updated_at": _iso(feed.updated_at),
    }


def serialize_federation_package(package: EngineeringKnowledgeFederationPackage) -> dict[str, Any]:
    return {
        "id": package.id,
        "feed_id": package.feed_id,
        "feed_name": package.feed.name if package.feed else None,
        "direction": package.direction,
        "package_id": package.package_id,
        "publisher_instance_id": package.publisher_instance_id,
        "schema_version": package.schema_version,
        "package_checksum": package.package_checksum,
        "signature": dict(package.signature or {}),
        "classification": package.classification,
        "trust_level": package.trust_level,
        "status": package.status,
        "review_status": package.review_status,
        "version": package.version,
        "dry_run_result": dict(package.dry_run_result or {}),
        "conflicts": list(package.conflicts or []),
        "retraction_refs": list(package.retraction_refs or []),
        "source_package_record_id": package.source_package_record_id,
        "created_by_user_id": package.created_by_user_id,
        "created_at": _iso(package.created_at),
        "updated_at": _iso(package.updated_at),
    }


def serialize_federation_sync_run(run: EngineeringKnowledgeFederationSyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "feed_id": run.feed_id,
        "feed_name": run.feed.name if run.feed else None,
        "package_record_id": run.package_record_id,
        "operation": run.operation,
        "status": run.status,
        "package_id": run.package_id,
        "package_checksum": run.package_checksum,
        "result": dict(run.result or {}),
        "errors": list(run.errors or []),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "created_by_user_id": run.created_by_user_id,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


__all__ = [
    "serialize_federation_feed",
    "serialize_federation_package",
    "serialize_federation_sync_run",
]
