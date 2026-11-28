"""Admin-panel helpers for stored secret rotation and expiry monitoring."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import StoredSecret
from ...secret import (
    list_secret_entries,
    list_secret_rotation_logs,
    revoke_secret_value,
    rotate_secret_value,
    serialize_secret_entry,
    update_secret_metadata,
)
from ..governance.admin_config_audit_service import record_admin_config_audit


async def list_stored_secrets_for_admin(
    db: AsyncSession,
    *,
    expiring_within_days: int | None = None,
    limit: int = 200,
):
    return await list_secret_entries(db, expiring_within_days=expiring_within_days, limit=limit)


async def list_secret_rotation_logs_for_admin(db: AsyncSession, *, limit: int = 100):
    return await list_secret_rotation_logs(db, limit=limit)


async def update_stored_secret_for_admin(
    db: AsyncSession,
    *,
    secret_id: str,
    payload: dict,
    actor_user_id: str | None = None,
):
    try:
        stored = await db.get(StoredSecret, secret_id)
        before = _stored_secret_audit_snapshot(stored)
        result = await update_secret_metadata(db, secret_id=secret_id, expires_at=payload.get("expires_at"))
        record_admin_config_audit(
            db,
            actor_user_id=actor_user_id,
            action="admin.security.stored_secret.metadata_updated",
            resource_type="stored_secret",
            resource_id=secret_id,
            project_id=stored.project_id if stored else None,
            before=before,
            after=result,
            details={
                "operation": "update_stored_secret_for_admin",
                "payload_keys": sorted(str(key) for key in payload),
            },
        )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def rotate_stored_secret_for_admin(
    db: AsyncSession,
    *,
    secret_id: str,
    rotated_by: str,
    payload: dict,
    actor_user_id: str | None = None,
):
    raw_value = str(payload.get("value") or "").strip()
    if not raw_value:
        raise HTTPException(status_code=422, detail="value is required")
    try:
        stored = await db.get(StoredSecret, secret_id)
        before = _stored_secret_audit_snapshot(stored)
        result = await rotate_secret_value(
            db,
            secret_id=secret_id,
            rotated_by=rotated_by,
            value=raw_value,
            expires_at=payload.get("expires_at"),
            note=payload.get("note"),
        )
        record_admin_config_audit(
            db,
            actor_user_id=actor_user_id or rotated_by,
            action="admin.security.stored_secret.rotated",
            resource_type="stored_secret",
            resource_id=secret_id,
            project_id=stored.project_id if stored else None,
            before=before,
            after=result,
            details={
                "operation": "rotate_stored_secret_for_admin",
                "payload_keys": sorted(str(key) for key in payload),
                "note_present": bool(str(payload.get("note") or "").strip()),
            },
        )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def revoke_stored_secret_for_admin(
    db: AsyncSession,
    *,
    secret_id: str,
    revoked_by: str,
    payload: dict,
    actor_user_id: str | None = None,
):
    try:
        stored = await db.get(StoredSecret, secret_id)
        before = _stored_secret_audit_snapshot(stored)
        result = await revoke_secret_value(
            db,
            secret_id=secret_id,
            revoked_by=revoked_by,
            note=payload.get("note"),
        )
        record_admin_config_audit(
            db,
            actor_user_id=actor_user_id or revoked_by,
            action="admin.security.stored_secret.revoked",
            resource_type="stored_secret",
            resource_id=secret_id,
            project_id=stored.project_id if stored else None,
            before=before,
            after=result,
            details={
                "operation": "revoke_stored_secret_for_admin",
                "payload_keys": sorted(str(key) for key in payload),
                "note_present": bool(str(payload.get("note") or "").strip()),
            },
        )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _stored_secret_audit_snapshot(secret: StoredSecret | None) -> dict:
    if secret is None:
        return {}
    return serialize_secret_entry(secret)
