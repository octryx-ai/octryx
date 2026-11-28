"""Registry entry (aggregate) lifecycle: retire a whole model policy."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.governed_revision import REGISTRY_STATUS_ACTIVE, REGISTRY_STATUS_RETIRED
from ...time_utils import utc_now
from .errors import REGISTRY_ENTRY_ALREADY_RETIRED, REGISTRY_ENTRY_RETIRED, RegistryRefusalError
from .governance import record_audit


def require_entry_active(entry: Any, **facts: Any) -> None:
    if entry.status == REGISTRY_STATUS_RETIRED:
        raise RegistryRefusalError(REGISTRY_ENTRY_RETIRED, **facts)


async def retire_entry(db: AsyncSession, *, kind: str, entry: Any, user: User) -> Any:
    if entry.status == REGISTRY_STATUS_RETIRED:
        raise RegistryRefusalError(REGISTRY_ENTRY_ALREADY_RETIRED, id=entry.id)
    entry.status = REGISTRY_STATUS_RETIRED
    entry.updated_at = utc_now()
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action=f"{kind}.retire_entry",
        resource_type=kind,
        project_id=entry.workspace_id,
        resource_id=entry.id,
        details={"workspace_id": entry.workspace_id, "previous_status": REGISTRY_STATUS_ACTIVE},
    )
    return entry


__all__ = ["require_entry_active", "retire_entry"]
