"""The named connection a platform service runs on, for service-only connectors."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .contract import NamedConnection, scope_key
from .descriptors import SERVICE_ONLY_CONNECTORS
from .grants import available_rows
from .store import list_platform_connections, resolved_config, to_value


async def _candidates(db: AsyncSession, connector: str, project_id: str | None) -> list[NamedConnection]:
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
    if connector not in SERVICE_ONLY_CONNECTORS:
        raise ValueError(f"{connector} is not a service-only connector")
    candidates = await _candidates(db, connector, project_id)
    key = scope_key(connector, instance) if instance else ""
    chosen = next((c for c in candidates if key in c.bound_scopes), None) if key else None
    return (chosen, await resolved_config(db, chosen)) if chosen is not None else None


__all__ = ["service_connection"]
