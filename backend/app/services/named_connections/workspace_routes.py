"""Build a Workspace's routes from the connections available there."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BuiltInToolConfig, ConnectorNamedConnection
from .contract import NAMED_CONNECTION_CONNECTORS, NamedConnection
from .grants import Grant, rows_with_grants
from .routes_model import (
    EMPTY_ROUTES,
    SCOPE_GLOBAL,
    SCOPE_WORKSPACE,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from .store import public_config, resolved_config, to_value
from .unbound_default import unbound_defaults


async def active_workspace_entries(db: AsyncSession, tool_names: Iterable[str], project_id: str) -> set[str]:
    wanted = sorted(set(tool_names))
    if not wanted:
        return set()
    result = await db.execute(
        select(BuiltInToolConfig.tool_name).where(
            BuiltInToolConfig.tool_name.in_(wanted),
            BuiltInToolConfig.project_id == project_id,
            BuiltInToolConfig.is_active.is_(False),
        )
    )
    switched_off = {str(name) for name in result.scalars().all()}
    return set(wanted) - switched_off


def ambiguous_of(own: Iterable[NamedConnection], shared: Iterable[NamedConnection]) -> frozenset[str]:
    def doubled(connections: Iterable[NamedConnection]) -> set[str]:
        seen: set[str] = set()
        twice: set[str] = set()
        for connection in connections:
            twice |= seen & connection.bound_scopes
            seen |= connection.bound_scopes
        return twice

    own = list(own)
    overridden = {key for connection in own for key in connection.bound_scopes}
    return frozenset(doubled(own) | (doubled(shared) - overridden))


def effective_of(
    own: Iterable[NamedConnection], shared: Iterable[NamedConnection]
) -> list[tuple[str, NamedConnection, frozenset[str]]]:
    own, shared = list(own), list(shared)
    ambiguous = ambiguous_of(own, shared)
    overridden: set[str] = set()
    effective = []
    for connection in own:
        overridden |= connection.bound_scopes
        effective.append((SCOPE_WORKSPACE, connection, frozenset(connection.bound_scopes - ambiguous)))
    for connection in shared:
        keys = connection.bound_scopes - overridden - ambiguous
        if keys:
            effective.append((SCOPE_GLOBAL, connection, frozenset(keys)))
    return effective


def split_routes(
    rows: list[tuple[ConnectorNamedConnection, Grant | None]], tool: str, default_ids: set[str]
) -> tuple[list[tuple[NamedConnection, Grant]], list[tuple[NamedConnection, Grant]]]:
    own, shared = [], []
    for row, grant in rows:
        if grant is None or row.tool_name != tool or str(row.id) in default_ids:
            continue
        (own if grant.own else shared).append((to_value(row), grant))
    return own, shared


async def effective_connections(
    db: AsyncSession, tool: str, project_id: str
) -> list[tuple[str, NamedConnection, frozenset[str]]]:
    own, shared = split_routes(await rows_with_grants(db, [tool], project_id), tool, set())
    return effective_of([c for c, _ in own], [c for c, _ in shared])


async def workspace_routes(
    db: AsyncSession,
    project_id: str | None,
    tool_names: Iterable[str] = NAMED_CONNECTION_CONNECTORS,
    *,
    secrets: bool = True,
) -> NamedConnectionRoutes:
    if not project_id:
        return EMPTY_ROUTES
    tools = list(dict.fromkeys(tool_names))
    active = await active_workspace_entries(db, tools, project_id)
    rows = await rows_with_grants(db, active, project_id)
    defaults = unbound_defaults(rows, [tool for tool in tools if tool in active])
    default_ids = {item.id for item in defaults.values()}
    resolved: list[ResolvedNamedConnection] = []
    ambiguous: set[tuple[str, str]] = set()
    for tool in (tool for tool in tools if tool in active):
        own, shared = split_routes(rows, tool, default_ids)
        grants = {connection.id: grant for connection, grant in (*own, *shared)}
        own_values, shared_values = [c for c, _ in own], [c for c, _ in shared]
        ambiguous |= {(tool, key) for key in ambiguous_of(own_values, shared_values)}
        for scope, connection, keys in effective_of(own_values, shared_values):
            grant = grants[connection.id]
            resolved.append(ResolvedNamedConnection(
                id=connection.id, tool_name=tool, name=connection.name, scope=scope, bound_scopes=keys,
                config=await resolved_config(db, connection) if secrets else public_config(connection),
                source=None if secrets else connection, is_active=grant.is_active, level=grant.level,
            ))
    return NamedConnectionRoutes(tuple(resolved), defaults=tuple(defaults[tool] for tool in tools if tool in defaults),
                                 ambiguous=frozenset(ambiguous))


__all__ = [
    "active_workspace_entries",
    "ambiguous_of",
    "effective_connections",
    "effective_of",
    "split_routes",
    "workspace_routes",
]
