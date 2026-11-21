"""Which connections a Workspace may use, read through ``config_effective.effective``.

A connection (``connector_named_connections`` row) is **available** in a Workspace when ``available_in`` is ``all``,
the Workspace is one of its ``connection_workspaces`` or owns it (``owner_workspace_id``); that is the same rule the
connections API shows (``services/connections/deviations.py``). For an available connection, :class:`Grant` carries
what the runtime enforces there:

- ``is_active``: a disabled connection stays in the routes (its keys never fall back to another account) and every
  use of it is refused (``connection_gate.REASON_CONNECTION_DISABLED``);
- ``level``: the agent tools level after the Workspace's deviation (``off`` < ``read`` < ``write``); a connection
  without a credential (a public GitHub connection) reads at most;
- ``deviation``: the Workspace's stored deviation (``knowledge`` / ``tickets`` narrow those uses);
- ``own``: the Workspace's own connection (a Workspace row of the per-connector named-connection admin,
  ``project_id``, or one it owns) - it takes precedence over the shared ones.

A row of the per-connector named-connection admin is available as :func:`named_connection_columns` says: a global row
``all``, a Workspace row ``selected`` plus that Workspace. Nothing here writes, and no secret is read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectionDeviation, ConnectionWorkspace, ConnectorNamedConnection
from ..config_effective import CONNECTION_RULES, Subject, effective
from ..secret import secret_ref_field_name
from .descriptors import descriptor_of

LEVEL_OFF = "off"
LEVEL_READ = "read"
LEVEL_WRITE = "write"
OWNER_WORKSPACE = "workspace"
USE_AGENT_TOOLS = "agent_tools"


@dataclass(frozen=True, slots=True)
class Grant:
    """What applies to one connection in one Workspace (see the module doc)."""

    is_active: bool = True
    level: str = LEVEL_WRITE
    deviation: dict[str, Any] | None = field(default=None, compare=False)
    own: bool = False

    def use(self, name: str) -> dict[str, Any]:
        """The Workspace's deviation of one use (``knowledge`` / ``tickets``), ``{}`` when it has none."""
        values = (self.deviation or {}).get(name)
        return dict(values) if isinstance(values, Mapping) else {}


def subject_of(row: ConnectorNamedConnection, workspace_ids: frozenset[str]) -> Subject:
    """The connection's availability; a Workspace row (``project_id``) is always available in its Workspace."""
    own = frozenset({row.project_id}) if row.project_id else frozenset()
    return Subject(available_in=str(row.available_in or "all"), workspace_ids=workspace_ids | own,
                   owner_workspace_id=row.owner_workspace_id)


def named_connection_columns(project_id: str | None) -> dict[str, Any]:
    """The connection columns of a row the named-connection admin creates: a Workspace row is ``selected`` (plus its
    ``connection_workspaces`` row), a global one ``all``; both serve every agent tool."""
    return {"available_in": "selected" if project_id else "all", "owner_kind": "platform",
            "agent_tools_level": LEVEL_WRITE}


def is_own(row: ConnectorNamedConnection, workspace_id: str) -> bool:
    return row.project_id == workspace_id or (
        row.owner_kind == OWNER_WORKSPACE and row.owner_workspace_id == workspace_id
    )


def has_credentials(tool: str, config: Mapping[str, Any] | None) -> bool:
    """Whether a connection of a type with secrets stores one (a type without secrets always counts as having)."""
    descriptor = descriptor_of(tool)
    if descriptor is None or not descriptor.secret_fields:
        return True
    values = config or {}
    return any(values.get(secret_ref_field_name(name)) or values.get(name) for name in descriptor.secret_fields)


def grant_of(row: ConnectorNamedConnection, workspace_id: str, workspace_ids: frozenset[str],
             deviation: Mapping[str, Any] | None) -> Grant | None:
    """The grant of ``row`` in ``workspace_id``; ``None`` when it is not available there."""
    level_deviation = {USE_AGENT_TOOLS: dict(deviation[USE_AGENT_TOOLS])} if (
        deviation and isinstance(deviation.get(USE_AGENT_TOOLS), Mapping)) else None
    result = effective(subject_of(row, workspace_ids), workspace_id,
                       {USE_AGENT_TOOLS: {"level": str(row.agent_tools_level or LEVEL_READ)}}, level_deviation,
                       CONNECTION_RULES)
    if not result.available:
        return None
    level = str((result.effective or {}).get(USE_AGENT_TOOLS, {}).get("level") or LEVEL_OFF)
    if level == LEVEL_WRITE and not has_credentials(str(row.tool_name), row.config):
        level = LEVEL_READ  # an anonymous (public) connection never writes
    return Grant(is_active=row.is_active is not False, level=level,
                 deviation=dict(deviation) if deviation else None, own=is_own(row, workspace_id))


async def connection_workspace_ids(db: AsyncSession, ids: list[str]) -> dict[str, frozenset[str]]:
    """The selected Workspaces (``connection_workspaces``) of each connection id."""
    found: dict[str, set[str]] = {connection_id: set() for connection_id in ids}
    if ids:
        rows = await db.execute(select(ConnectionWorkspace.connection_id, ConnectionWorkspace.workspace_id)
                                .where(ConnectionWorkspace.connection_id.in_(ids)))
        for connection_id, workspace_id in rows.all():
            found[str(connection_id)].add(str(workspace_id))
    return {key: frozenset(value) for key, value in found.items()}


async def _deviations(db: AsyncSession, ids: list[str], workspace_id: str) -> dict[str, dict]:
    if not ids:
        return {}
    rows = await db.execute(select(ConnectionDeviation).where(ConnectionDeviation.connection_id.in_(ids),
                                                              ConnectionDeviation.workspace_id == workspace_id))
    return {str(row.connection_id): dict(row.fields or {}) for row in rows.scalars().all()}


async def rows_with_grants(
    db: AsyncSession, tool_names: Iterable[str], workspace_id: str
) -> list[tuple[ConnectorNamedConnection, Grant | None]]:
    """Every connection of ``tool_names`` with its grant in ``workspace_id`` (``None``: not available there), by
    name; three queries: the rows, their Workspaces and this Workspace's deviations."""
    wanted = sorted(set(tool_names))
    if not wanted or not workspace_id:
        return []
    rows = (await db.execute(
        select(ConnectorNamedConnection).where(ConnectorNamedConnection.tool_name.in_(wanted))
        .order_by(ConnectorNamedConnection.name, ConnectorNamedConnection.id)
    )).scalars().all()
    ids = [str(row.id) for row in rows]
    workspaces, deviations = await connection_workspace_ids(db, ids), await _deviations(db, ids, workspace_id)
    return [(row, grant_of(row, workspace_id, workspaces[str(row.id)], deviations.get(str(row.id)))) for row in rows]


async def available_rows(
    db: AsyncSession, tool_names: Iterable[str], workspace_id: str
) -> list[tuple[ConnectorNamedConnection, Grant]]:
    """The connections of ``tool_names`` available in ``workspace_id`` with their grants, by name."""
    return [(row, grant) for row, grant in await rows_with_grants(db, tool_names, workspace_id) if grant is not None]


async def grant_for(db: AsyncSession, row: ConnectorNamedConnection, workspace_id: str) -> Grant | None:
    """The grant of one connection in ``workspace_id`` (``None``: not available there)."""
    ids = [str(row.id)]
    return grant_of(row, workspace_id, (await connection_workspace_ids(db, ids))[ids[0]],
                    (await _deviations(db, ids, workspace_id)).get(ids[0]))


__all__ = [
    "LEVEL_OFF",
    "LEVEL_READ",
    "LEVEL_WRITE",
    "Grant",
    "available_rows",
    "connection_workspace_ids",
    "grant_for",
    "grant_of",
    "has_credentials",
    "is_own",
    "named_connection_columns",
    "rows_with_grants",
    "subject_of",
]
