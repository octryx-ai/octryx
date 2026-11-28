"""Which connections a Workspace may use, read through ``config_effective.effective``."""

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
    is_active: bool = True
    level: str = LEVEL_WRITE
    deviation: dict[str, Any] | None = field(default=None, compare=False)
    own: bool = False

    def use(self, name: str) -> dict[str, Any]:
        values = (self.deviation or {}).get(name)
        return dict(values) if isinstance(values, Mapping) else {}


def subject_of(row: ConnectorNamedConnection, workspace_ids: frozenset[str]) -> Subject:
    own = frozenset({row.project_id}) if row.project_id else frozenset()
    return Subject(available_in=str(row.available_in or "all"), workspace_ids=workspace_ids | own,
                   owner_workspace_id=row.owner_workspace_id)


def named_connection_columns(project_id: str | None) -> dict[str, Any]:
    return {"available_in": "selected" if project_id else "all", "owner_kind": "platform",
            "agent_tools_level": LEVEL_WRITE}


def is_own(row: ConnectorNamedConnection, workspace_id: str) -> bool:
    return row.project_id == workspace_id or (
        row.owner_kind == OWNER_WORKSPACE and row.owner_workspace_id == workspace_id
    )


def has_credentials(tool: str, config: Mapping[str, Any] | None) -> bool:
    descriptor = descriptor_of(tool)
    if descriptor is None or not descriptor.secret_fields:
        return True
    values = config or {}
    return any(values.get(secret_ref_field_name(name)) or values.get(name) for name in descriptor.secret_fields)


def grant_of(row: ConnectorNamedConnection, workspace_id: str, workspace_ids: frozenset[str],
             deviation: Mapping[str, Any] | None) -> Grant | None:
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
    return [(row, grant) for row, grant in await rows_with_grants(db, tool_names, workspace_id) if grant is not None]


async def grant_for(db: AsyncSession, row: ConnectorNamedConnection, workspace_id: str) -> Grant | None:
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
