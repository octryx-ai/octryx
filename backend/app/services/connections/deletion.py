"""``DELETE /api/v1/admin/connections/{id}``: only without active uses (``409 connection_in_use`` with the list).

The connection's secrets are released (``secret/release.py``), its Workspace rows and deviations go with it, and the
audit keeps its name, type and Workspaces (never a secret).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectionDeviation, ConnectionWorkspace, ConnectorNamedConnection
from ..secret.release import ExcludedHolder, config_secret_refs, release_unreferenced_secrets
from . import store
from .contract import CODE_IN_USE
from .errors_and_usage import in_use
from .writes import audit, audit_state

AUDIT_DELETED = "admin.connection.deleted"


async def delete_connection(db: AsyncSession, row: ConnectorNamedConnection, *, actor_id: str) -> dict[str, Any]:
    from fastapi import HTTPException

    users = await in_use(db, row)
    if users:
        raise HTTPException(status_code=409, detail={
            "code": CODE_IN_USE, "message": "The connection is still used; remove or move these uses first.",
            "uses": users})
    workspaces = sorted((await store.workspaces_of(db, [row.id]))[row.id])
    before = audit_state(row, workspaces)
    released = await release_unreferenced_secrets(
        db, config_secret_refs(dict(row.config or {})),
        excluded=ExcludedHolder(table="connector_named_connections", row_id=row.id))
    audit(db, actor_id, AUDIT_DELETED, row, before=before, after={},
          details={"stored_entries": released.to_payload()})
    await db.execute(delete(ConnectionDeviation).where(ConnectionDeviation.connection_id == row.id))
    await db.execute(delete(ConnectionWorkspace).where(ConnectionWorkspace.connection_id == row.id))
    await db.delete(row)
    await db.flush()
    return {"status": "deleted", "id": row.id}


__all__ = ["AUDIT_DELETED", "delete_connection"]
