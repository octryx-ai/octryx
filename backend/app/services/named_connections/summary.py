"""The connections a Workspace's calls can run on, by id, for policy authors."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .contract import DEFAULT_CONNECTION_NAME
from .workspace_routes import workspace_routes


async def workspace_connection_summary(db: AsyncSession, project_id: str) -> dict[str, list[dict[str, Any]]]:
    routes = await workspace_routes(db, project_id, secrets=False)
    summary: dict[str, list[dict[str, Any]]] = {}
    for connection in routes.connections:
        summary.setdefault(connection.tool_name, []).append(
            {"id": connection.id, "name": connection.name, "scope": connection.scope,
             "binds": sorted(connection.bound_scopes)}
        )
    for listed in summary.values():
        listed.append({"id": DEFAULT_CONNECTION_NAME, "name": DEFAULT_CONNECTION_NAME, "scope": "connector"})
    return summary


__all__ = ["workspace_connection_summary"]
