"""Which local model licences the launchers may use (``local_models.permissive_only``)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig

PERMISSIVE_ONLY_KEY = "local_models.permissive_only"
AUDIT_PERMISSIVE_ONLY = "admin.local_models.permissive_only_updated"


async def permissive_only(db: AsyncSession) -> bool:
    row = await db.get(SystemConfig, PERMISSIVE_ONLY_KEY)
    return not (row is not None and str(row.value or "").strip().lower() == "false")


async def set_permissive_only(db: AsyncSession, *, value: object, actor_id: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError("permissive_only must be true or false")
    before = await permissive_only(db)
    row = await db.get(SystemConfig, PERMISSIVE_ONLY_KEY)
    if row is None:
        row = SystemConfig(key=PERMISSIVE_ONLY_KEY,
                           description="Launchers use only permissively licensed local models (Apache-2.0, MIT)")
        db.add(row)
    row.value = "true" if value else "false"
    db.add(AuditLog(user_id=actor_id, action=AUDIT_PERMISSIVE_ONLY, resource_type="system_config",
                    resource_id=PERMISSIVE_ONLY_KEY, details={"before": before, "after": value}))
    await db.flush()
    return value


__all__ = ["AUDIT_PERMISSIVE_ONLY", "PERMISSIVE_ONLY_KEY", "permissive_only", "set_permissive_only"]
