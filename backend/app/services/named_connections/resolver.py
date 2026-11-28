"""Which connection serves a scope item: the one resolver every consumer uses."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .contract import DEFAULT_CONNECTION_NAME, require_descriptor, scope_key
from .descriptor import listed_entries
from .descriptors import DESCRIPTORS
from .routes_model import NAMED_CONNECTIONS_KEY, NamedConnectionRoutes, ResolvedNamedConnection, routes_of
from .store import resolved_config

ALLOWLIST_FIELDS = {
    connector: descriptor.allowlist.field for connector, descriptor in DESCRIPTORS.items() if descriptor.allowlist
}


async def with_secrets(db: AsyncSession | None, connection: ResolvedNamedConnection) -> ResolvedNamedConnection:
    if connection.source is None or db is None:
        return connection
    return replace(connection, config=await resolved_config(db, connection.source), source=None)


def _listed(raw: Any) -> list[Any]:
    return listed_entries(raw)


def _narrowed(tool: str, base: dict, keys: frozenset[str]) -> list[Any]:
    allowlist = require_descriptor(tool).allowlist
    rules = {scope_key(tool, allowlist.rule_key(entry)): entry for entry in _listed(base.get(allowlist.field))}
    narrowed = [rules.get(key, allowlist.entry(key)) for key in sorted(keys)]
    return allowlist.narrow(narrowed, keys) if allowlist.narrow is not None else narrowed


def _without_unit(tool: str, config: dict) -> dict:
    descriptor = require_descriptor(tool)
    dropped = descriptor.unit_keys | set(descriptor.named_drops)
    return {key: value for key, value in config.items() if key not in dropped and key != NAMED_CONNECTIONS_KEY}


def connection_config(
    base: dict, tool: str, routes: NamedConnectionRoutes, connection: ResolvedNamedConnection | None
) -> dict:
    descriptor = require_descriptor(tool)
    allowlist = descriptor.allowlist
    if connection is not None:
        unit = descriptor.unit_keys
        own = {key: value for key, value in connection.config.items() if key in unit}
        scoped = {**_without_unit(tool, base), **own}
        if allowlist is not None:
            scoped[allowlist.field] = _narrowed(tool, base, connection.bound_scopes)
        return scoped
    bound = routes.bound_keys(tool)
    default = {key: value for key, value in base.items() if key != NAMED_CONNECTIONS_KEY}
    if not bound or allowlist is None:
        return default
    listed = _listed(default.get(allowlist.field))
    kept = [entry for entry in listed if scope_key(tool, allowlist.rule_key(entry)) not in bound]
    single = allowlist.single_key_field
    if single and scope_key(tool, default.get(single)) in bound:
        default.pop(single, None)
    if listed and not kept:
        # Every key the default listed is bound elsewhere: it serves nothing (an empty Jira or
        # ServiceNow allowlist would read as unrestricted), so it has no target and no credential.
        return _without_unit(tool, default) | {allowlist.field: []}
    if allowlist.field in default:
        default[allowlist.field] = kept
    return default


def serving_connection(config: dict | None, tool: str) -> ResolvedNamedConnection | None:
    routes = routes_of(config)
    descriptor = DESCRIPTORS.get(tool)
    if routes.unavailable or descriptor is None:
        return None
    return next((c for c in routes.of(tool) if c.is_active and descriptor.usable(c.config)), None)


def default_allows(tool: str, config: dict, key: object) -> bool:
    served = require_descriptor(tool).default_keys(config)
    return served is None or scope_key(tool, key) in served


def connection_name(connection: ResolvedNamedConnection | None) -> str:
    return connection.name if connection is not None else DEFAULT_CONNECTION_NAME


def connection_ref(connection: ResolvedNamedConnection | None) -> str:
    return connection.id if connection is not None else DEFAULT_CONNECTION_NAME


__all__ = [
    "ALLOWLIST_FIELDS",
    "connection_config",
    "connection_name",
    "connection_ref",
    "default_allows",
    "serving_connection",
    "with_secrets",
]
