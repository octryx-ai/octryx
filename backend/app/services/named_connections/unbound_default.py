"""A connector's one available connection that binds no key is the Workspace's default connection."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from .contract import require_descriptor
from .grants import Grant
from .routes_model import DefaultConnection, NamedConnectionRoutes
from .store import resolved_config, to_value


def unbound_defaults(rows: list[tuple[ConnectorNamedConnection, Grant | None]],
                     tools: list[str]) -> dict[str, DefaultConnection]:
    found: dict[str, DefaultConnection] = {}
    for tool in tools:
        unbound = [(row, grant) for row, grant in rows
                   if row.tool_name == tool and grant is not None and grant.is_active and not (row.bound_scopes or [])]
        if len(unbound) == 1:
            row, grant = unbound[0]
            found[tool] = DefaultConnection(id=str(row.id), tool_name=tool, name=str(row.name), level=grant.level)
    return found


async def apply_default(db: AsyncSession, config: dict, default: DefaultConnection) -> dict:
    unit_keys = require_descriptor(default.tool_name).unit_keys
    stripped = {key: value for key, value in config.items() if key not in unit_keys}
    row = await db.get(ConnectorNamedConnection, default.id)
    if row is None:
        return stripped
    resolved = await resolved_config(db, to_value(row))
    return {**stripped, **{key: value for key, value in resolved.items() if key in unit_keys}}


async def apply_defaults(db: AsyncSession, config: dict, routes: NamedConnectionRoutes) -> dict:
    for default in routes.defaults:
        config = await apply_default(db, config, default)
    return config


__all__ = ["apply_default", "apply_defaults", "unbound_defaults"]
