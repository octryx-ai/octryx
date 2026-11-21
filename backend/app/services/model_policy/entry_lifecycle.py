"""Registry entry (aggregate) lifecycle: retire a whole model policy.

Retiring an entry is terminal and stops all *new* use; it never rewrites history:

* ``status`` becomes ``retired``; there is no way back;
* every revision keeps its state, digest and approval (published revisions stay
  readable and exportable, and stay ``published`` in the audit trail);
* nothing new can use it: a reference to a retired policy resolves to no aliases;
* saving a draft, importing onto it, submitting and publishing are refused with
  ``registry_entry_retired``. Retiring a single revision is still allowed.

Retiring an already retired entry is refused with ``registry_entry_already_retired``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.governed_revision import REGISTRY_STATUS_ACTIVE, REGISTRY_STATUS_RETIRED
from ...time_utils import utc_now
from .errors import REGISTRY_ENTRY_ALREADY_RETIRED, REGISTRY_ENTRY_RETIRED, RegistryRefusalError
from .governance import record_audit


def require_entry_active(entry: Any, **facts: Any) -> None:
    """Refuse any forward change (draft, import, submit, publish) on a retired entry."""
    if entry.status == REGISTRY_STATUS_RETIRED:
        raise RegistryRefusalError(REGISTRY_ENTRY_RETIRED, **facts)


async def retire_entry(db: AsyncSession, *, kind: str, entry: Any, user: User) -> Any:
    """``active -> retired`` for a whole registry entry; audited as ``<kind>.retire_entry``."""
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
        resource_id=entry.id,
        details={"workspace_id": entry.workspace_id, "previous_status": REGISTRY_STATUS_ACTIVE},
    )
    return entry


__all__ = ["require_entry_active", "retire_entry"]
