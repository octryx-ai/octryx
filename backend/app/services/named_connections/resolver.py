"""Which connection serves a scope item: the one resolver every consumer uses.

For a scope item (a binding key of the connector's descriptor: a Confluence space key, a Jira project key,
a ServiceNow table, a Kubernetes cluster, ...; nested keys try the most specific binding first):

1. a connection available in the Workspace that binds it exactly serves it: the Workspace's own connections
   first, then the shared ones (an own binding overrides a shared binding of the same key: the shared
   connection then serves only its other keys in this Workspace, see :func:`effective_connections`); which
   connections are available, active and at which agent tools level is read through ``config_effective``
   (``grants.py``, ``workspace_routes.py``); a key two connections of the same precedence bind is
   refused, never chosen;
2. otherwise the connector's default entry serves it, but only as today's rules allow (its own
   allowlist, or the keys it declares, ``ConnectorDescriptor.default_keys``) and never for a key some
   named connection binds;
3. otherwise the item is refused with ``connection_not_configured_for_scope``.

Named connections apply only while the Workspace's own entry of the connector exists and is active:
that entry stays the connector's single access switch for the Workspace (a disabled connector has
no account at all). A request is never served by another named connection's credential: nothing in
this module chooses by order, by fallback or by trying.

:func:`connection_config` is the effective configuration of one connection: the default entry's
non-connection settings (page allowlists, limits) with the connection unit replaced
by the named connection's and the allowlist narrowed to its bound scopes. The default connection's
allowlist loses every bound key; a default whose allowlist only held bound keys serves nothing (its
target and credential are removed, so it fails closed instead of turning into "unrestricted"). Only the
connection unit (``contract.connection_keys``) of a named connection reaches that config; any other key
stored on the connection is dropped.

The routes travel inside a merged config under :data:`NAMED_CONNECTIONS_KEY`, typed as
:class:`NamedConnectionRoutes` (``routes_model.py``, attached by ``tool_config._attach_named_connections``).
:func:`routes_of` reads them:

- no key: the Workspace has no named connections, calls pass through;
- a typed value: the routes;
- any other value under the key (a plain value from a policy bundle or ``Project.config``, a JSON
  round trip that lost the type): :data:`ROUTES_UNAVAILABLE`, a fail-closed marker. The tool router
  refuses every call of a routed connector with ``named_connection_routes_unavailable``
  instead of running it on the default connection, whose allowlist would still hold bound keys.

Secrets: the routes attached to a merged config carry each named connection's fields without secrets
(``workspace_routes(..., secrets=False)``); the tool router resolves the secret of exactly the
connection a call runs on (:func:`with_secrets`), never every connection's.
"""

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
    """``connection`` with its own secrets resolved; without a session it keeps none (fails closed)."""
    if connection.source is None or db is None:
        return connection
    return replace(connection, config=await resolved_config(db, connection.source), source=None)


def _listed(raw: Any) -> list[Any]:
    return listed_entries(raw)


def _narrowed(tool: str, base: dict, keys: frozenset[str]) -> list[Any]:
    """The allowlist for exactly ``keys``: the default's own rule of a key when it has one, else the key's rule."""
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
    """The effective config of ``connection`` (``None``: the default connection) over the merged ``base``."""
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
    """The first usable named connection that serves ``tool`` in the merged ``config``, or ``None``.

    The routes exist only while the Workspace's own entry of the connector is active
    (:func:`workspace_routes`), so a connection here means "enabled and served". Untyped routes
    (:data:`ROUTES_UNAVAILABLE`) serve nothing. Which keys a call may reach stays the router's decision.
    """
    routes = routes_of(config)
    descriptor = DESCRIPTORS.get(tool)
    if routes.unavailable or descriptor is None:
        return None
    return next((c for c in routes.of(tool) if c.is_active and descriptor.usable(c.config)), None)


def default_allows(tool: str, config: dict, key: object) -> bool:
    """Today's rule of the default connection for one key (its allowlist or declared keys; see the descriptor)."""
    served = require_descriptor(tool).default_keys(config)
    return served is None or scope_key(tool, key) in served


def connection_name(connection: ResolvedNamedConnection | None) -> str:
    return connection.name if connection is not None else DEFAULT_CONNECTION_NAME


def connection_ref(connection: ResolvedNamedConnection | None) -> str:
    """The identity of a connection: its id (``default`` for the default entry). Names may repeat across scopes."""
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
