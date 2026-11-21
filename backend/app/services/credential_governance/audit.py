"""Secret access audit: recording governance events, the audited export scrub and the audit log query."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.credential_governance import AUDIT_ACTION_EXPORT_SCRUB, SecretAccessAuditLog
from .scrubbing import scrub_secrets_from_payload


async def _audit(
    db: AsyncSession,
    *,
    secret_id: str | None,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    actor_user_id: str | None,
    outcome: str = "success",
    context: dict[str, Any] | None = None,
) -> None:
    db.add(SecretAccessAuditLog(
        secret_id=secret_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        outcome=outcome,
        context_json=context or {},
    ))
    # No flush here — caller controls transaction boundary


async def scrub_and_audit_export(
    db: AsyncSession,
    *,
    payload: Any,
    actor_user_id: str | None,
    export_context: str = "",
) -> Any:
    """Scrub secrets from a payload and emit one export_scrub audit event per path.

    Use this in data_transfer exports, trace serialization, and domain pack exports.
    """
    scrubbed, paths = scrub_secrets_from_payload(payload)
    if paths:
        await _audit(
            db,
            secret_id=None,
            action=AUDIT_ACTION_EXPORT_SCRUB,
            entity_type=None,
            entity_id=None,
            actor_user_id=actor_user_id,
            outcome="scrubbed",
            context={"scrubbed_paths": paths, "export_context": export_context},
        )
        await db.flush()
    return scrubbed


# ---------------------------------------------------------------------------
# Public API: Audit log query
# ---------------------------------------------------------------------------


async def list_audit_log(
    db: AsyncSession,
    *,
    secret_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[SecretAccessAuditLog]:
    """Query the secret access audit log with optional filters."""
    stmt = select(SecretAccessAuditLog).order_by(SecretAccessAuditLog.created_at.desc())
    if secret_id:
        stmt = stmt.where(SecretAccessAuditLog.secret_id == secret_id)
    if entity_type:
        stmt = stmt.where(SecretAccessAuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(SecretAccessAuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(SecretAccessAuditLog.action == action)
    stmt = stmt.limit(max(1, min(int(limit or 100), 500)))
    return list((await db.execute(stmt)).scalars().all())
