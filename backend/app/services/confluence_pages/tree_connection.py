"""Which saved connection the page picker reads a space with.

The picker edits a Confluence entry's ``confluence_allowed_pages`` (the global entry, or a Workspace's limits); a
space is read with the connection that serves it, by the one resolver's rule (``named_connections/resolver.py``):
a named connection that binds the space (in a Workspace its own first, then the global ones it does not override),
else the default entry when its own allowlist allows the space, else the read is refused
(``connection_not_configured_for_scope``). Nothing is tried in turn and no other connection's credential is used.
Only saved values count: a space typed but not saved is not readable yet.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.named_connections.routes_model import (
    REASON_NOT_CONFIGURED_FOR_SCOPE,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.workspace_routes import workspace_routes

from ..named_connections.connection_gate import target_refusal
from ..named_connections.contract import CONFLUENCE
from ..named_connections.resolver import connection_config, default_allows, with_secrets
from ..named_connections.store import list_platform_connections, public_config, to_value
from ..named_connections.unbound_default import apply_defaults
from ..secret import resolve_secret_refs
from ..tool_config import get_tool_config
from ..tool_config.connection_fields import global_config_for_scope
from .tree import refuse

CODE_NOT_CONFIGURED = "connector_not_configured"
CODE_NOT_ENABLED_IN_WORKSPACE = "connector_not_enabled_in_workspace"


async def _serving_config(
    db: AsyncSession, base: dict[str, Any], routes: NamedConnectionRoutes, space_key: str
) -> dict[str, Any]:
    match = routes.match(CONFLUENCE, space_key)
    refused = target_refusal(routes, CONFLUENCE, match) or (
        "connection_ambiguous" if routes.ambiguous_keys(CONFLUENCE, [space_key]) else None)
    if refused:  # a disabled, unavailable or ambiguous connection reads nothing
        raise refuse(409, refused, f"The connection serving space {space_key} cannot be used ({refused}).")
    if match is not None:
        return connection_config(base, CONFLUENCE, routes, await with_secrets(db, match))
    default = connection_config(base, CONFLUENCE, routes, None)
    if space_key.upper() in routes.bound_keys(CONFLUENCE) or not default_allows(CONFLUENCE, default, space_key):
        raise refuse(409, REASON_NOT_CONFIGURED_FOR_SCOPE,
                     f"No saved connection serves space {space_key}: add it to the allowed spaces and save first.")
    return default


async def _global_base(db: AsyncSession) -> dict[str, Any]:
    entry = await get_tool_config(db, CONFLUENCE, None)
    if entry is None or not entry.is_active or not entry.config:
        return {}
    return await resolve_secret_refs(db, dict(entry.config), tool_name=CONFLUENCE, project_id=None)


async def global_space_config(db: AsyncSession, space_key: str) -> dict[str, Any]:
    """The effective config of the connection that serves ``space_key`` globally (secrets of that one only)."""
    base = await _global_base(db)
    if not base:
        raise refuse(409, CODE_NOT_CONFIGURED, "Save and test the Confluence connector first.")
    rows = await list_platform_connections(db, CONFLUENCE)
    routes = NamedConnectionRoutes(tuple(
        ResolvedNamedConnection(
            id=connection.id, tool_name=CONFLUENCE, name=connection.name, scope="global",
            bound_scopes=connection.bound_scopes, config=public_config(connection), source=connection,
            is_active=row.is_active is not False,
        )
        for row, connection in ((row, to_value(row)) for row in rows)
    ))
    return await _serving_config(db, base, routes, space_key)


async def workspace_space_config(db: AsyncSession, project_id: str, space_key: str) -> dict[str, Any]:
    """The same for a Workspace: its saved entry over the global one, its named connections before the global ones."""
    entry = await get_tool_config(db, CONFLUENCE, project_id)
    if entry is None or not entry.is_active:
        raise refuse(409, CODE_NOT_ENABLED_IN_WORKSPACE,
                     "Enable Confluence for this Workspace and save access first.")
    own = dict(entry.config or {})
    base = global_config_for_scope(CONFLUENCE, await _global_base(db), own)
    if own:
        base.update(await resolve_secret_refs(db, own, tool_name=CONFLUENCE, project_id=project_id))
    if not base:
        raise refuse(409, CODE_NOT_CONFIGURED, "Save and test the Confluence connector first.")
    routes = await workspace_routes(db, project_id, (CONFLUENCE,), secrets=False)
    return await _serving_config(db, await apply_defaults(db, base, routes), routes, space_key)


__all__ = ["CODE_NOT_CONFIGURED", "CODE_NOT_ENABLED_IN_WORKSPACE", "global_space_config", "workspace_space_config"]
