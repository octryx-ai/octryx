"""Every Workspace's connections of one connector, for the global list (Automation → Connectors).

The global list shows the global scope only; a Workspace's own accounts were visible only inside that Workspace.
This overview lists, read-only, per active Workspace: its named connections and its own default connection (a Workspace
connector entry with its own target). Per entry: Workspace id and name, connection id and name, bound keys
(a default: its allowlist keys) and the unit's non-secret fields. Never a secret value or a ``*_secret_ref``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import BuiltInToolConfig, ConnectorNamedConnection, Project
from ...named_connections.contract import DEFAULT_CONNECTION_NAME
from ...named_connections.descriptor import rule_key
from ...named_connections.descriptors import descriptor_of
from .named_connection_unit import public_fields


def _default_keys(tool: str, config: dict[str, Any]) -> list[str]:
    allowlist = descriptor_of(tool).allowlist
    raw = config.get(allowlist.field) if allowlist else None
    keys = [rule_key(entry) for entry in raw] if isinstance(raw, list) else []
    return [key for key in keys if key]


async def workspace_connections(db: AsyncSession, tool: str) -> list[dict[str, Any]]:
    """Named and own default connections of ``tool`` in every Workspace, by Workspace name then connection name."""
    usable = descriptor_of(tool).usable_field
    names = dict((await db.execute(select(Project.id, Project.name).where(Project.is_active.is_(True), Project.access_mode != "private"))).all())
    listed: list[dict[str, Any]] = []
    entries = await db.execute(
        select(BuiltInToolConfig).where(BuiltInToolConfig.tool_name == tool, BuiltInToolConfig.project_id.is_not(None))
    )
    for entry in entries.scalars():
        config = dict(entry.config or {})
        if entry.project_id not in names or not config.get(usable):
            continue  # an access switch with limits only: the Workspace uses the global connection
        listed.append({
            "workspace_id": entry.project_id, "workspace_name": names[entry.project_id],
            "id": DEFAULT_CONNECTION_NAME, "name": DEFAULT_CONNECTION_NAME, "active": bool(entry.is_active),
            "bound_scopes": _default_keys(tool, config), "fields": public_fields(tool, config),
        })
    rows = await db.execute(
        select(ConnectorNamedConnection).where(
            ConnectorNamedConnection.tool_name == tool, ConnectorNamedConnection.project_id.is_not(None)
        )
    )
    for row in rows.scalars():
        if row.project_id not in names:
            continue
        listed.append({
            "workspace_id": row.project_id, "workspace_name": names[row.project_id],
            "id": row.id, "name": row.name, "active": True,
            "bound_scopes": list(row.bound_scopes or []), "fields": public_fields(tool, dict(row.config or {})),
        })
    listed.sort(key=lambda item: (str(item["workspace_name"]).lower(), item["id"] != DEFAULT_CONNECTION_NAME,
                                  item["name"].lower()))
    return listed


async def workspace_connection_counts(db: AsyncSession) -> dict[str, int]:
    """How many Workspace connections each named-connection connector has (Automation → Connectors shows a card for a
    connector that has some, even without a global entry)."""
    from ...named_connections.descriptors import DESCRIPTORS

    counts = {tool: len(await workspace_connections(db, tool)) for tool in DESCRIPTORS}
    return {tool: count for tool, count in counts.items() if count}


async def with_workspace_connection_counts(db: AsyncSession, connectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The global connector list, each with ``workspace_connections`` (its count of Workspace connections)."""
    counts = await workspace_connection_counts(db)
    return [{**connector, "workspace_connections": counts.get(str(connector.get("tool_name") or ""), 0)}
            for connector in connectors]


__all__ = ["with_workspace_connection_counts", "workspace_connection_counts", "workspace_connections"]
