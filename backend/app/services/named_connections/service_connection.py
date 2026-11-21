"""The named connection a platform service runs on, for service-only connectors.

A service-only connector (:data:`descriptors.SERVICE_ONLY_CONNECTORS`, today Jenkins) has no agent tool, so no tool
router picks its connection; the service names it explicitly. :func:`service_connection` answers exactly one
active connection available in the Workspace (its own first, then a shared one) or ``None``: the connection that
binds ``instance`` (bound scopes are unique per connector and scope).

Nothing is chosen by order, by fallback or by trying; the returned connection carries its own secrets only.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .contract import NamedConnection, scope_key
from .descriptors import SERVICE_ONLY_CONNECTORS
from .grants import available_rows
from .store import list_platform_connections, resolved_config, to_value


async def _candidates(db: AsyncSession, connector: str, project_id: str | None) -> list[NamedConnection]:
    """The active connections available in the Workspace (its own first), or every platform one."""
    if not project_id:
        return [to_value(row) for row in await list_platform_connections(db, connector) if row.is_active]
    granted = [(row, grant) for row, grant in await available_rows(db, [connector], project_id)
               if grant.is_active]
    return [to_value(row) for row, grant in sorted(granted, key=lambda item: not item[1].own)]


async def service_connection(
    db: AsyncSession,
    connector: str,
    project_id: str | None,
    *,
    instance: str | None = None,
) -> tuple[NamedConnection, dict] | None:
    """The connection serving ``connector`` for a platform service in ``project_id`` and its resolved config."""
    if connector not in SERVICE_ONLY_CONNECTORS:
        raise ValueError(f"{connector} is not a service-only connector")
    candidates = await _candidates(db, connector, project_id)
    key = scope_key(connector, instance) if instance else ""
    chosen = next((c for c in candidates if key in c.bound_scopes), None) if key else None
    return (chosen, await resolved_config(db, chosen)) if chosen is not None else None


__all__ = ["service_connection"]
