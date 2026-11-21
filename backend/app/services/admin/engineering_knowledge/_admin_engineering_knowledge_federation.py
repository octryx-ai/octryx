"""Federation-panel and quality-panel helpers for Engineering Knowledge admin services."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...engineering_knowledge import (
    create_engineering_knowledge_federation_feed,
    disable_engineering_knowledge_federation_feed,
    get_engineering_knowledge_federation_dashboard,
    get_engineering_knowledge_quality_dashboard,
    get_federation_usage_impact,
    import_signed_engineering_knowledge_package,
    preview_federation_export_control,
    publish_signed_engineering_knowledge_package,
    record_engineering_knowledge_federation_sync_failure,
    record_federated_knowledge_usage,
    review_imported_engineering_knowledge_package,
)
from ._admin_engineering_knowledge_common import _optional_id


async def get_engineering_knowledge_quality_panel(
    db: AsyncSession,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    return await get_engineering_knowledge_quality_dashboard(db, limit=limit)


async def get_engineering_knowledge_federation_panel(db: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    return await get_engineering_knowledge_federation_dashboard(db, limit=limit)


async def create_engineering_knowledge_federation_panel_feed(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await create_engineering_knowledge_federation_feed(db, payload=payload, current_user=current_user)


async def publish_engineering_knowledge_federation_panel_package(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await publish_signed_engineering_knowledge_package(
        db,
        package=dict(payload.get("package") or {}),
        feed_id=_optional_id(payload.get("feed_id")),
        current_user=current_user,
    )


async def preview_engineering_knowledge_federation_panel_export(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    export_policy = dict(payload.get("export_policy") or {})
    if payload.get("review_approved") is not None:
        export_policy["review_approved"] = bool(payload.get("review_approved"))
    if payload.get("reviewer_role"):
        export_policy["reviewer_role"] = str(payload.get("reviewer_role") or "").strip()
    result = await preview_federation_export_control(
        db,
        node_ids=[str(item).strip() for item in payload.get("node_ids", []) if str(item or "").strip()],
        export_policy=export_policy,
    )
    result["requested_by"] = getattr(current_user, "id", None)
    return result


async def import_engineering_knowledge_federation_panel_package(
    db: AsyncSession,
    *,
    feed_id: str,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed_id,
        package=dict(payload.get("package") or {}),
        verification_key=str(payload.get("verification_key") or "").strip() or None,
        current_user=current_user,
    )


async def review_engineering_knowledge_federation_panel_import(
    db: AsyncSession,
    *,
    package_record_id: str,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await review_imported_engineering_knowledge_package(
        db,
        package_record_id=package_record_id,
        action=str(payload.get("action") or "").strip(),
        payload=payload,
        current_user=current_user,
    )


async def disable_engineering_knowledge_federation_panel_feed(
    db: AsyncSession,
    *,
    feed_id: str,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await disable_engineering_knowledge_federation_feed(
        db,
        feed_id=feed_id,
        reason=str(payload.get("reason") or "Emergency disabled from Federation panel").strip(),
        current_user=current_user,
    )


async def record_engineering_knowledge_federation_panel_usage(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await record_federated_knowledge_usage(
        db,
        package_record_id=_optional_id(payload.get("package_record_id")),
        package_id=str(payload.get("package_id") or "").strip(),
        run_id=str(payload.get("run_id") or "").strip(),
        session_id=_optional_id(payload.get("session_id")),
        fact_ids=[str(item).strip() for item in payload.get("fact_ids", []) if str(item or "").strip()],
        current_user=current_user,
    )


async def get_engineering_knowledge_federation_panel_usage(
    db: AsyncSession,
    *,
    package_id: str | None = None,
    package_record_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await get_federation_usage_impact(
        db,
        package_id=package_id,
        package_record_id=package_record_id,
        limit=limit,
    )


async def record_engineering_knowledge_federation_panel_sync_failure(
    db: AsyncSession,
    *,
    feed_id: str,
    payload: dict[str, Any],
    current_user: Any,
) -> dict[str, Any]:
    return await record_engineering_knowledge_federation_sync_failure(
        db,
        feed_id=feed_id,
        error=str(payload.get("error") or "").strip(),
        operation=str(payload.get("operation") or "poll").strip() or "poll",
        current_user=current_user,
    )
