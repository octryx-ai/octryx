"""The typed routes a merged config carries for the tool router (with their grants).

:class:`NamedConnectionRoutes` travels inside a merged config under :data:`NAMED_CONNECTIONS_KEY`
(``tool_config._attach_named_connections``); :func:`routes_of` reads it (no key: no routes; any untyped value:
:data:`ROUTES_UNAVAILABLE`, a fail-closed marker). Built by ``workspace_routes.py``; read by ``resolver.py``,
``route_plan.py``, ``connection_gate.py`` and the consumers outside the package.

- ``connections``: the named connections in precedence order (the Workspace's own first, then the shared ones), each
  with its grant (``is_active``, agent tools ``level``);
- ``defaults``: per connector, the one available connection that binds no key, which is the Workspace's default
  connection (:class:`DefaultConnection`, ``unbound_default.py``); absent when there is none or more than one;
- ``ambiguous``: ``(connector, key)`` pairs two connections of the same precedence bind; no connection serves them
  and the router refuses them (``connection_ambiguous``, ``needs_configuration``) instead of choosing one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .contract import DEFAULT_CONNECTION_NAME, NamedConnection, require_descriptor, scope_key
from .grants import LEVEL_WRITE

NAMED_CONNECTIONS_KEY = "named_connections"
REASON_NOT_CONFIGURED_FOR_SCOPE = "connection_not_configured_for_scope"
REASON_SCOPE_SPANS_CONNECTIONS = "scope_spans_connections"
REASON_ROUTES_UNAVAILABLE = "named_connection_routes_unavailable"
REASON_CONNECTION_DISABLED = "connection_disabled"
REASON_CONNECTION_NOT_AVAILABLE = "connection_not_available"
SCOPE_WORKSPACE = "workspace"
SCOPE_GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class ResolvedNamedConnection:
    """One named connection; ``config`` never appears in a repr.

    ``source`` set: ``config`` holds no secret yet, ``resolver.with_secrets`` resolves them for this connection.
    ``is_active`` / ``level``: the connection's grant in the Workspace (``grants.py``).
    """

    id: str
    tool_name: str
    name: str
    scope: str
    bound_scopes: frozenset[str]
    config: dict = field(repr=False, compare=False)
    source: NamedConnection | None = field(default=None, repr=False, compare=False)
    is_active: bool = True
    level: str = LEVEL_WRITE


@dataclass(frozen=True, slots=True)
class DefaultConnection:
    """The connection that is a connector's default connection in this Workspace (``unbound_default.py``).

    It is always active and available here; ``level`` is its agent tools level in the Workspace.
    """

    id: str
    tool_name: str
    name: str
    level: str = LEVEL_WRITE


@dataclass(frozen=True, slots=True)
class NamedConnectionRoutes:
    """The connections a Workspace's requests may use (see the module doc)."""

    connections: tuple[ResolvedNamedConnection, ...] = ()
    unavailable: bool = False
    defaults: tuple[DefaultConnection, ...] = ()
    ambiguous: frozenset[tuple[str, str]] = frozenset()

    def of(self, tool_name: str) -> tuple[ResolvedNamedConnection, ...]:
        return tuple(connection for connection in self.connections if connection.tool_name == tool_name)

    def has(self, tool_name: str) -> bool:
        return bool(self.of(tool_name)) or any(tool == tool_name for tool, _ in self.ambiguous)

    def default_of(self, tool_name: str) -> DefaultConnection | None:
        return next((item for item in self.defaults if item.tool_name == tool_name), None)

    def ambiguous_keys(self, tool_name: str, keys: tuple[str, ...] | list[str]) -> list[str]:
        """The keys among ``keys`` two connections of the same precedence bind (most specific binding first)."""
        if not self.ambiguous:
            return []
        candidates = require_descriptor(tool_name).binding.candidates
        return [key for key in keys
                if any((tool_name, wanted) in self.ambiguous for wanted in candidates(scope_key(tool_name, key)))]

    def match(self, tool_name: str, key: object) -> ResolvedNamedConnection | None:
        """The connection binding ``key``; for nested keys the most specific binding (``a/b`` before ``a``)."""
        connections = self.of(tool_name)
        for wanted in require_descriptor(tool_name).binding.candidates(scope_key(tool_name, key)):
            found = next((c for c in connections if wanted in c.bound_scopes), None)
            if found is not None:
                return found
        return None

    def served_by(self, tool_name: str, keys: Iterable[object]) -> frozenset[str]:
        """The connections ``keys`` are read with (:meth:`match`): each binding's id, ``default`` for an unbound key."""
        return frozenset(found.id if (found := self.match(tool_name, key)) is not None else DEFAULT_CONNECTION_NAME
                         for key in keys)

    def bound_keys(self, tool_name: str) -> frozenset[str]:
        """Every key a named connection binds, ambiguous ones included (the default never serves them)."""
        keys: set[str] = {key for tool, key in self.ambiguous if tool == tool_name}
        for connection in self.of(tool_name):
            keys |= connection.bound_scopes
        return frozenset(keys)

    def __str__(self) -> str:  # a JSON dump with ``default=str`` sees names and scopes only
        return repr(self)


EMPTY_ROUTES = NamedConnectionRoutes()
ROUTES_UNAVAILABLE = NamedConnectionRoutes(unavailable=True)


def routes_of(config: dict | None) -> NamedConnectionRoutes:
    """The routes the platform attached to a merged config; any untyped value is :data:`ROUTES_UNAVAILABLE`."""
    value = (config or {}).get(NAMED_CONNECTIONS_KEY)
    if value is None:
        return EMPTY_ROUTES
    return value if type(value) is NamedConnectionRoutes else ROUTES_UNAVAILABLE


__all__ = [
    "EMPTY_ROUTES",
    "NAMED_CONNECTIONS_KEY",
    "REASON_CONNECTION_DISABLED",
    "REASON_CONNECTION_NOT_AVAILABLE",
    "REASON_NOT_CONFIGURED_FOR_SCOPE",
    "REASON_ROUTES_UNAVAILABLE",
    "REASON_SCOPE_SPANS_CONNECTIONS",
    "ROUTES_UNAVAILABLE",
    "SCOPE_GLOBAL",
    "SCOPE_WORKSPACE",
    "DefaultConnection",
    "NamedConnectionRoutes",
    "ResolvedNamedConnection",
    "routes_of",
]
