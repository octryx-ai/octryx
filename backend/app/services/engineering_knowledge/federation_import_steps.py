"""Steps of importing a signed knowledge package: dry run, status, sync run and audit."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeFederationPackage,
    EngineeringKnowledgeFederationSyncRun,
    User,
)
from .federation_import_conflicts import classify_federation_import_conflicts
from .federation_operations import add_federation_audit_event
from .federation_package import dry_run_import_engineering_knowledge_package
from .federation_records import _create_sync_run, _update_feed_sync_state


async def _import_dry_run(
    db: AsyncSession,
    package: dict[str, Any],
    *,
    verification_key: str | None,
) -> dict[str, Any]:
    dry_run = await dry_run_import_engineering_knowledge_package(db, package, verification_key=verification_key)
    dry_run["conflicts"] = await classify_federation_import_conflicts(
        db,
        package,
        base_conflicts=dry_run.get("conflicts") or [],
    )
    dry_run["importable_node_count"] = max(0, int(dry_run.get("node_count") or 0) - len(dry_run["conflicts"]))
    return dry_run


def _import_status(package: dict[str, Any], dry_run: dict[str, Any]) -> str:
    status = "failed" if dry_run["status"] == "blocked" else "pending_review"
    if package.get("retractions"):
        status = "retraction_received" if dry_run["status"] != "blocked" else "failed"
    return status


def _import_operation(retraction_result: dict[str, Any], action: str) -> str:
    return (
        "retraction_sync"
        if retraction_result["retracted_count"]
        else ("import" if action == "created" else action)
    )


async def _record_import_run(
    db: AsyncSession,
    *,
    feed: EngineeringKnowledgeFederationFeed,
    record: EngineeringKnowledgeFederationPackage,
    operation: str,
    run_status: str,
    result: dict[str, Any],
    dry_run: dict[str, Any],
    current_user: User,
) -> EngineeringKnowledgeFederationSyncRun:
    run = await _create_sync_run(
        db,
        feed=feed,
        package_record=record,
        operation=operation,
        status=run_status,
        result=result,
        errors=dry_run["errors"],
        current_user=current_user,
    )
    await _update_feed_sync_state(
        feed,
        status=run_status,
        error="; ".join(error["message"] for error in dry_run["errors"]),
    )
    return run


async def _audit_import(
    db: AsyncSession,
    *,
    record: EngineeringKnowledgeFederationPackage,
    feed: EngineeringKnowledgeFederationFeed,
    operation: str,
    run_status: str,
    dry_run: dict[str, Any],
    current_user: User,
) -> None:
    await add_federation_audit_event(
        db,
        action="policy_blocked" if run_status == "failed" else operation,
        resource_type="engineering_knowledge_federation_package",
        resource_id=record.id,
        details={
            "package_id": record.package_id,
            "publisher_instance_id": record.publisher_instance_id,
            "feed_id": feed.id,
            "status": run_status,
            "error_codes": [str(error.get("code") or "") for error in dry_run["errors"]],
        },
        current_user=current_user,
    )
