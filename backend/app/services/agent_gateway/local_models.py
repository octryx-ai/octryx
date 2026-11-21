"""Which local model licences the launchers may use.

Some small local models are not open for every company: Liquid AI's LFM family (the launcher's router model d1-2B,
LFM2.5, LFM3) is under the "LFM Open License v1.0", which allows commercial use only below USD 10M annual revenue.
The platform switch ``local_models.permissive_only`` (``SystemConfig``, default **on**) lets the launchers use only
permissive licences (Apache-2.0, MIT); a platform admin switches it off, and even then a person loads a restricted
model only on an explicit choice after the licence notice. The launchers read it in ``/client-policy``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig

PERMISSIVE_ONLY_KEY = "local_models.permissive_only"
AUDIT_PERMISSIVE_ONLY = "admin.local_models.permissive_only_updated"


async def permissive_only(db: AsyncSession) -> bool:
    """On unless a platform admin stored ``false``."""
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
