"""The platform kill switch for device runs: ``system_config`` key ``device_runs.enabled``.

Absent means enabled (the Workspace opt-in is off by default, so nothing runs until a Workspace turns it on).
Switching it off refuses every new device turn and stops every running one within seconds.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig

CONFIG_KEY = "device_runs.enabled"
AUDIT_ACTION = "admin.device_runs.platform_switch"


async def device_runs_platform_enabled(db: AsyncSession) -> bool:
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == CONFIG_KEY))).scalar_one_or_none()
    return row is None or str(row.value or "").strip().lower() != "false"


async def set_device_runs_platform_enabled(db: AsyncSession, *, enabled: bool, actor_id: str) -> None:
    """Write the switch (audited); switching off stops every running device turn. Flushes."""
    row = (await db.execute(select(SystemConfig).where(SystemConfig.key == CONFIG_KEY))).scalar_one_or_none()
    if row is None:
        row = SystemConfig(key=CONFIG_KEY, description="Platform kill switch for remote device sessions")
        db.add(row)
    row.value = "true" if enabled else "false"
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="system_config", resource_id=CONFIG_KEY,
                    details={"enabled": enabled}))
    await db.flush()
    if not enabled:
        from .jobs import stop_active_jobs

        await stop_active_jobs(db, actor_id=actor_id, reason="platform_switch_off")


__all__ = ["CONFIG_KEY", "device_runs_platform_enabled", "set_device_runs_platform_enabled"]
