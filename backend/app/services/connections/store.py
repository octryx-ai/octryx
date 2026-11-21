"""Reading connections and their Workspace rows. Connections are ``connector_named_connections`` rows."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectionDeviation, ConnectionWorkspace, ConnectorNamedConnection, Project


async def list_rows(db: AsyncSession, connection_type: str | None = None) -> list[ConnectorNamedConnection]:
    stmt = select(ConnectorNamedConnection).order_by(ConnectorNamedConnection.tool_name, ConnectorNamedConnection.name)
    if connection_type:
        stmt = stmt.where(ConnectorNamedConnection.tool_name == connection_type)
    return list((await db.execute(stmt)).scalars().all())


async def get_row(db: AsyncSession, connection_id: str) -> ConnectorNamedConnection | None:
    return await db.get(ConnectorNamedConnection, str(connection_id or ""))


async def workspaces_of(db: AsyncSession, ids: Iterable[str]) -> dict[str, frozenset[str]]:
    wanted = list(set(ids))
    found: dict[str, set[str]] = {connection_id: set() for connection_id in wanted}
    if wanted:
        rows = await db.execute(select(ConnectionWorkspace.connection_id, ConnectionWorkspace.workspace_id)
                                .where(ConnectionWorkspace.connection_id.in_(wanted)))
        for connection_id, workspace_id in rows.all():
            found[str(connection_id)].add(str(workspace_id))
    return {key: frozenset(value) for key, value in found.items()}


async def deviations_of(db: AsyncSession, ids: Iterable[str]) -> dict[str, list[ConnectionDeviation]]:
    wanted = list(set(ids))
    found: dict[str, list[ConnectionDeviation]] = {connection_id: [] for connection_id in wanted}
    if wanted:
        rows = await db.execute(select(ConnectionDeviation).where(ConnectionDeviation.connection_id.in_(wanted))
                                .order_by(ConnectionDeviation.workspace_id))
        for row in rows.scalars().all():
            found[str(row.connection_id)].append(row)
    return found


async def deviation_of(db: AsyncSession, connection_id: str, workspace_id: str) -> ConnectionDeviation | None:
    return (await db.execute(select(ConnectionDeviation).where(
        ConnectionDeviation.connection_id == connection_id, ConnectionDeviation.workspace_id == workspace_id
    ))).scalar_one_or_none()


async def workspace_names(db: AsyncSession, ids: Iterable[str | None]) -> dict[str, str]:
    wanted = sorted({str(item) for item in ids if item})
    if not wanted:
        return {}
    rows = await db.execute(select(Project.id, Project.name).where(Project.id.in_(wanted)))
    return {str(pid): str(name or pid) for pid, name in rows.all()}


async def set_workspaces(db: AsyncSession, connection_id: str, workspace_ids: Iterable[str]) -> None:
    """Replace the connection's ``connection_workspaces`` rows with ``workspace_ids``."""
    wanted = set(workspace_ids)
    current = (await workspaces_of(db, [connection_id]))[connection_id]
    for row in (await db.execute(select(ConnectionWorkspace).where(
            ConnectionWorkspace.connection_id == connection_id))).scalars().all():
        if row.workspace_id not in wanted:
            await db.delete(row)
    for workspace_id in sorted(wanted - current):
        db.add(ConnectionWorkspace(connection_id=connection_id, workspace_id=workspace_id))
    await db.flush()


async def existing_workspaces(db: AsyncSession, ids: Iterable[str]) -> set[str]:
    wanted = list(set(ids))
    if not wanted:
        return set()
    return {str(pid) for pid in (await db.execute(select(Project.id).where(Project.id.in_(wanted)))).scalars()}


__all__ = [
    "deviation_of",
    "deviations_of",
    "existing_workspaces",
    "get_row",
    "list_rows",
    "set_workspaces",
    "workspace_names",
    "workspaces_of",
]
