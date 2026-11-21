"""Who uses a named connection: Workspaces and Knowledge Source Sync connectors, by connection id.

The answer follows the one resolver (``resolver.py``), never a second rule:

- **A Workspace uses a connection** for the keys it serves there: its own connection for its bound keys;
  a shared connection available there for its bound keys no own connection binds (the own binding
  wins), and only while the Workspace's own entry of the connector is active (the access switch).
- **A Work intake uses a connection** it names by id (``WorkItemSyncConfig.connection_id``);
  a delete stops its runs (``intake_connection_unavailable``) until another connection is picked.
- **A Knowledge connector uses a connection** for each of its scope items that connection serves in the
  connector's Workspace. A connector pinned by id (``scope.connection_id``) uses only that connection; a
  pin whose items resolve elsewhere is listed with ``pin_mismatch`` (its runs are refused), so a delete or
  a rebind shows it.

Only ids, names and scope keys are returned; no config, URL or secret is read.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BuiltInToolConfig, Project, WorkItemSyncConfig
from ...models.project.knowledge_source_sync import KnowledgeSourceConnector
from .contract import scope_key
from .workspace_routes import effective_connections


async def _active_workspaces(db: AsyncSession, tool: str, project_id: str | None) -> dict[str, str]:
    """``{project id: name}`` of the Workspaces whose own entry of ``tool`` is active (one, for a Workspace)."""
    stmt = (
        select(Project.id, Project.name)
        .join(BuiltInToolConfig, BuiltInToolConfig.project_id == Project.id)
        .where(BuiltInToolConfig.tool_name == tool, BuiltInToolConfig.is_active.is_(True))
    )
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)
    return {str(pid): str(name or pid) for pid, name in (await db.execute(stmt)).all()}


def _empty() -> dict[str, list]:
    return {"workspaces": [], "knowledge_connectors": [], "work_intakes": []}


async def _work_intakes(db: AsyncSession, usage: dict[str, dict[str, list]]) -> None:
    rows = (
        await db.execute(
            select(WorkItemSyncConfig, Project.name)
            .join(Project, Project.id == WorkItemSyncConfig.project_id)
            .where(WorkItemSyncConfig.connection_id.in_(list(usage)))
            .order_by(Project.name, WorkItemSyncConfig.name)
        )
    ).all()
    for row, workspace_name in rows:
        usage[str(row.connection_id)]["work_intakes"].append(
            {"workspace_id": row.project_id, "workspace_name": str(workspace_name or row.project_id),
             "intake_id": row.id, "name": row.name, "active": bool(row.is_active)}
        )


async def connection_usage(
    db: AsyncSession, tool: str, project_id: str | None, connection_ids: Iterable[str]
) -> dict[str, dict[str, list]]:
    """``{connection id: {"workspaces": [...], "knowledge_connectors": [...]}}`` for connections of one scope.

    ``project_id`` None: global connections, used across every Workspace; else that Workspace only.
    """
    from ..knowledge.sources.sync.scope_connections import scope_items  # sync builds on this package

    wanted = set(connection_ids)
    usage = {connection_id: _empty() for connection_id in wanted}
    if not wanted:
        return usage
    await _work_intakes(db, usage)
    workspaces = await _active_workspaces(db, tool, project_id)
    if not workspaces:
        return usage
    serving: dict[str, dict[str, str]] = {}  # project id -> scope key -> connection id
    for pid, workspace_name in workspaces.items():
        effective = await effective_connections(db, tool, pid)  # the connections available there
        serving[pid] = {key: connection.id for _, connection, keys in effective for key in keys}
        for _, connection, keys in effective:
            if connection.id in wanted:
                usage[connection.id]["workspaces"].append({"id": pid, "name": workspace_name, "scopes": sorted(keys)})
    connectors = (
        await db.execute(
            select(KnowledgeSourceConnector)
            .where(KnowledgeSourceConnector.kind == tool, KnowledgeSourceConnector.project_id.in_(list(workspaces)))
            .order_by(KnowledgeSourceConnector.project_id, KnowledgeSourceConnector.connector_key)
        )
    ).scalars().all()
    for row in connectors:
        scope = dict(row.scope or {})
        pin = scope.get("connection_id") or None
        keys = [scope_key(tool, item) for item in scope_items(tool, scope)]
        served: dict[str, list[str]] = {}
        for key in keys:
            ref = serving[row.project_id].get(key)
            if ref is not None:
                served.setdefault(ref, []).append(key)
        for connection_id in wanted:
            mine = served.get(connection_id, [])
            if (pin and pin != connection_id) or (not mine and pin != connection_id):
                continue  # pinned to another connection: it never reads with this one
            usage[connection_id]["knowledge_connectors"].append(
                {
                    "workspace_id": row.project_id,
                    "workspace_name": workspaces[row.project_id],
                    "connector_key": row.connector_key,
                    "scopes": sorted(mine),
                    "pinned": pin == connection_id,
                    # Pinned here but some item resolves elsewhere: its runs are refused (connection_pin_mismatch).
                    "pin_mismatch": pin == connection_id and len(mine) != len(keys),
                }
            )
    return usage


__all__ = ["connection_usage"]
