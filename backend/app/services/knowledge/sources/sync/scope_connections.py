"""The connection of each scope item of a Source Sync connector (named connections)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.workspace_routes import effective_connections, workspace_routes

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_KIND_KUBERNETES,
    CONNECTOR_KIND_SERVICENOW,
)
from ....named_connections.contract import DEFAULT_CONNECTION_NAME
from ....named_connections.resolver import connection_config, connection_ref, default_allows
from .config_within import scope_within_connection
from .confluence_scope import scope_space_keys
from .connections import connection_from_config, merged_tool_config, resolve_connection
from .contract import (
    REASON_CONNECTION_AMBIGUOUS,
    REASON_CONNECTION_DISABLED,
    REASON_CONNECTION_NOT_CONFIGURED,
    REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE,
    REASON_CONNECTION_PIN_MISMATCH,
    REASON_CONNECTION_PIN_UNKNOWN,
    REASON_OWN_CONNECTION_INCOMPLETE,
    REASON_SCOPE_SPANS_CONNECTIONS,
    ConnectorError,
)
from .git_bitbucket import linked_git_connection
from .linked_connection import check_linked_grant, linked_scope
from .servicenow_scope import scope_tables

NAMED_KINDS = (CONNECTOR_KIND_CONFLUENCE, CONNECTOR_KIND_JIRA, CONNECTOR_KIND_SERVICENOW, CONNECTOR_KIND_KUBERNETES)


@dataclass(frozen=True, slots=True)
class ScopeConnections:
    connections: dict  # connection ref (named connection id, or "default") -> connection
    by_key: dict  # scope key (as configured) -> connection ref
    named: bool = False
    names: dict = field(default_factory=dict)  # connection ref -> connection name (for logs and reports)

    def described(self) -> dict[str, str]:
        return {key: f"{self.names.get(ref, ref)} ({ref})" for key, ref in self.by_key.items()}

    @property
    def single(self):
        names = set(self.by_key.values()) or set(self.connections)
        return self.connections[next(iter(names))] if len(names) == 1 else None


def scope_items(kind: str, scope: dict) -> tuple[str, ...]:
    if kind == CONNECTOR_KIND_CONFLUENCE:
        return tuple(str(key) for key in scope_space_keys(scope))
    if kind == CONNECTOR_KIND_SERVICENOW:
        return tuple(str(key) for key in scope_tables(scope))
    if kind == CONNECTOR_KIND_KUBERNETES:
        return (str(scope.get("cluster") or ""),)
    return tuple(str(key) for key in scope.get("project_keys") or ())


async def resolve_scope_connections(db: AsyncSession, *, kind: str, project_id: str, scope: dict,
                                    connection_id: str | None = None) -> ScopeConnections:
    if connection_id and kind in NAMED_KINDS:
        scope = await linked_scope(db, kind=kind, project_id=project_id, scope=scope, connection_id=connection_id,
                                   items=scope_items(kind, scope))
    elif connection_id:
        await check_linked_grant(db, project_id=project_id, connection_id=connection_id)
        if kind == CONNECTOR_KIND_GIT_REPOSITORY:
            # A repository linked to a Bitbucket connection reads with exactly that connection (git_bitbucket.py).
            connected = await linked_git_connection(db, project_id, scope, connection_id)
            if connected is not None:
                return ScopeConnections({connection_id: connected}, {})
    pin = scope.get("connection_id")
    try:
        scoped = await _resolve(db, kind=kind, project_id=project_id, scope=scope)
    except ConnectorError as error:
        if pin and error.reason == REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE:
            # The pinned connection no longer serves an item (deleted or rebound): name the pin.
            raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH) from None
        raise
    if pin and any(ref != pin for ref in (set(scoped.by_key.values()) or set(scoped.connections))):
        raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH)
    return scoped


async def require_known_pin(db: AsyncSession, *, kind: str, project_id: str, scope: dict) -> None:
    pin = scope.get("connection_id")
    if not pin or pin == DEFAULT_CONNECTION_NAME:
        return
    usable = set()
    if kind in NAMED_KINDS:
        usable = {connection.id for _, connection, _ in await effective_connections(db, kind, project_id)}
    if pin not in usable:
        raise ConnectorError(REASON_CONNECTION_PIN_UNKNOWN)


async def _resolve(db: AsyncSession, *, kind: str, project_id: str, scope: dict) -> ScopeConnections:
    routes = await workspace_routes(db, project_id, (kind,)) if kind in NAMED_KINDS else None
    if routes is None or not routes.has(kind):
        connection = await resolve_connection(db, kind=kind, project_id=project_id, scope=scope)
        return ScopeConnections({DEFAULT_CONNECTION_NAME: connection}, {})
    base = await merged_tool_config(db, kind, project_id)
    if base is None:  # the routes exist only while the entry is active; re-checked, never assumed
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    connections: dict = {}
    by_key: dict[str, str] = {}
    names: dict[str, str] = {}
    if routes.ambiguous_keys(kind, list(scope_items(kind, scope))):
        raise ConnectorError(REASON_CONNECTION_AMBIGUOUS)  # two connections bind an item; an admin must decide
    for key in scope_items(kind, scope):
        named = routes.match(kind, key)
        ref = connection_ref(named)
        if ref not in connections:
            config = connection_config(base, kind, routes, named)
            if named is None and not default_allows(kind, config, key):
                raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
            if named is not None and not named.is_active:
                raise ConnectorError(REASON_CONNECTION_DISABLED)
            connection = connection_from_config(kind, config)
            if connection is None:
                # A named connection without its URL or credential is incomplete; it never borrows one.
                incomplete = REASON_OWN_CONNECTION_INCOMPLETE if named is not None else None
                raise ConnectorError(incomplete or REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
            connections[ref] = connection
            names[ref] = named.name if named is not None else DEFAULT_CONNECTION_NAME
        elif named is None and not default_allows(kind, connection_config(base, kind, routes, None), key):
            raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
        by_key[key] = ref
    if not connections:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
    if kind != CONNECTOR_KIND_CONFLUENCE and len(connections) > 1:
        raise ConnectorError(REASON_SCOPE_SPANS_CONNECTIONS)
    return ScopeConnections(connections, by_key, named=True, names=names)


def _sub_scope(scope: dict, keys: set[str]) -> dict:
    return {
        "spaces": [space for space in scope.get("spaces") or () if str(space) in keys],
        "page_trees": [tree for tree in scope.get("page_trees") or () if str(tree.get("space_key") or "") in keys],
    }


def scope_allowed(kind: str, scope: dict, scoped: ScopeConnections) -> bool:
    single = scoped.single
    if single is not None:
        return scope_within_connection(kind, scope, single)
    for ref, connection in scoped.connections.items():
        keys = {key for key, served_by in scoped.by_key.items() if served_by == ref}
        if not scope_within_connection(kind, _sub_scope(scope, keys), connection):
            return False
    return True


__all__ = ["ScopeConnections", "require_known_pin", "resolve_scope_connections", "scope_allowed", "scope_items"]
