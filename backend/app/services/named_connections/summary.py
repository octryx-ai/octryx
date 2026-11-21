"""The connections a Workspace's calls can run on, by id, for policy authors.

The policy summary (``data_classification/workspace_policy_summary.py``) lists them so an admin can write a
Cedar policy over ``context.connections`` (e.g. a connection only read via the governed client). Only ids,
names, scopes and bound keys; never a config value or a secret.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .contract import DEFAULT_CONNECTION_NAME
from .workspace_routes import workspace_routes


async def workspace_connection_summary(db: AsyncSession, project_id: str) -> dict[str, list[dict[str, Any]]]:
    """``{connector: [connection ...]}`` for each connector with named connections the Workspace can use."""
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
