"""A connector's one available connection that binds no key is the Workspace's default connection.

A connection that binds no key serves nothing as a named route, so without this a connection that is "Working" and
available in every Workspace but binds no repository would leave every tool of its connector "not active". When
exactly one available, active connection of the connector binds no key, it is the Workspace's default connection
(:func:`unbound_defaults`); two such connections stay unrouted (never chosen by order).

Where the default connection serves a use, its unit (fields and its own secrets, ``store.resolved_config``) replaces
the entry's in the merged config (:func:`apply_default`); everything else of the entry (allowlists, limits) stays.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from .contract import require_descriptor
from .grants import Grant
from .routes_model import DefaultConnection, NamedConnectionRoutes
from .store import resolved_config, to_value


def unbound_defaults(rows: list[tuple[ConnectorNamedConnection, Grant | None]],
                     tools: list[str]) -> dict[str, DefaultConnection]:
    """``{tool: default connection}`` for each connector of ``tools`` with exactly one unbound connection."""
    found: dict[str, DefaultConnection] = {}
    for tool in tools:
        unbound = [(row, grant) for row, grant in rows
                   if row.tool_name == tool and grant is not None and grant.is_active and not (row.bound_scopes or [])]
        if len(unbound) == 1:
            row, grant = unbound[0]
            found[tool] = DefaultConnection(id=str(row.id), tool_name=tool, name=str(row.name), level=grant.level)
    return found


async def apply_default(db: AsyncSession, config: dict, default: DefaultConnection) -> dict:
    """``config`` with the default connection's unit instead of the entry's (removed when the row is gone)."""
    unit_keys = require_descriptor(default.tool_name).unit_keys
    stripped = {key: value for key, value in config.items() if key not in unit_keys}
    row = await db.get(ConnectorNamedConnection, default.id)
    if row is None:
        return stripped
    resolved = await resolved_config(db, to_value(row))
    return {**stripped, **{key: value for key, value in resolved.items() if key in unit_keys}}


async def apply_defaults(db: AsyncSession, config: dict, routes: NamedConnectionRoutes) -> dict:
    """:func:`apply_default` for every connector of ``routes`` with a default connection."""
    for default in routes.defaults:
        config = await apply_default(db, config, default)
    return config


__all__ = ["apply_default", "apply_defaults", "unbound_defaults"]
