"""A use that names its connection by id: an intake (``work_item_sync_configs.connection_id``) or a Knowledge source
(``knowledge_source_connectors.connection_id``).

:func:`resolve_linked` answers which route the use reads through and what its grant allows, or refuses with a fixed
code (``needs_configuration``), never another connection:

- the default connection's id (``unbound_default.py``) or ``default`` is the Workspace's default connection;
- a connection of the routes is that connection; a connection that exists but is not available in the Workspace is
  ``connection_not_available``; an id that is no connection, or one that serves nothing here, is ``None`` (the
  caller's "gone" path, unchanged);
- a disabled connection is refused (``connection_gate.use_refusal``);
- the Workspace's deviation of the use (``knowledge`` / ``tickets``) applies (:func:`deviation_refusal`): ``enabled``
  false is ``connection_use_disabled``; a ``scope`` is the upper bound of the keys the use may read, a key outside it
  is ``scope_not_allowed`` (the use's own scope must be narrowed; nothing is dropped silently). Where keys nest (a
  hierarchical binding: GitHub ``owner/repo``, GitLab ``group/project``), an entry covers itself and every key under
  it (``octryx-ai`` covers ``octryx-ai/bench``; ``octryx-ai/bench`` covers only itself), in the binding's case.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from .connection_gate import use_refusal
from .contract import DEFAULT_CONNECTION_NAME, scope_key
from .descriptors import descriptor_of
from .grants import Grant, grant_for
from .routes_model import REASON_CONNECTION_NOT_AVAILABLE, NamedConnectionRoutes, ResolvedNamedConnection

CODE_USE_DISABLED = "connection_use_disabled"
CODE_SCOPE_NOT_ALLOWED = "scope_not_allowed"
USE_KNOWLEDGE = "knowledge"
USE_TICKETS = "tickets"


class LinkedConnectionRefusedError(Exception):
    """The use may not read through its connection; ``code`` is fixed, ``scopes`` the keys outside its scope."""

    def __init__(self, code: str, scopes: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.scopes = list(scopes or [])

    def detail(self) -> dict:
        detail = {"state": "needs_configuration", "code": self.code, "reason": self.code}
        return {**detail, "scopes": self.scopes} if self.scopes else detail


@dataclass(frozen=True, slots=True)
class LinkedConnection:
    """``ref``: the routing ref (a named connection's id, or ``default``); ``connection_id``: the connection row
    (``None`` for the default entry); ``grant``: its grant in the Workspace."""

    ref: str
    target: ResolvedNamedConnection | None = field(repr=False)
    connection_id: str | None = None
    grant: Grant | None = field(default=None, compare=False)


def deviation_refusal(grant: Grant | None, use: str, tool: str,
                      keys: Iterable[object]) -> LinkedConnectionRefusedError | None:
    values = grant.use(use) if grant is not None else {}
    if values.get("enabled") is False:
        return LinkedConnectionRefusedError(CODE_USE_DISABLED)
    scope = values.get("scope")
    if not isinstance(scope, Mapping):
        return None
    allowed = {scope_key(tool, item) for items in scope.values() if isinstance(items, list) for item in items}
    descriptor = descriptor_of(tool)
    wanted = {scope_key(tool, key) for key in keys if str(key or "").strip()}
    outside = sorted(key for key in wanted if not any(
        candidate in allowed for candidate in (descriptor.binding.candidates(key) if descriptor else (key,))))
    return LinkedConnectionRefusedError(CODE_SCOPE_NOT_ALLOWED, outside) if outside else None


async def resolve_linked(
    db: AsyncSession, project_id: str, tool: str, connection_id: object, routes: NamedConnectionRoutes,
) -> LinkedConnection | None:
    """The route of a use naming ``connection_id`` (see the module doc); ``None`` when no such connection exists."""
    wanted = connection_id.strip() if isinstance(connection_id, str) else ""
    wanted = wanted or DEFAULT_CONNECTION_NAME
    default = routes.default_of(tool)
    if wanted == DEFAULT_CONNECTION_NAME or (default is not None and wanted == default.id):
        if default is None:
            return LinkedConnection(DEFAULT_CONNECTION_NAME, None)
        row = await db.get(ConnectorNamedConnection, default.id)
        grant = await grant_for(db, row, project_id) if row is not None else None
        return LinkedConnection(DEFAULT_CONNECTION_NAME, None, default.id, grant)
    target = next((item for item in routes.of(tool) if item.id == wanted), None)
    row = await db.get(ConnectorNamedConnection, wanted)
    if target is None:
        # Available but serving nothing here (its keys are overridden) stays the caller's "gone" path.
        if row is not None and row.tool_name == tool and await grant_for(db, row, project_id) is None:
            raise LinkedConnectionRefusedError(REASON_CONNECTION_NOT_AVAILABLE)
        return None
    refused = use_refusal(routes, tool, target)
    if refused:
        raise LinkedConnectionRefusedError(refused)
    return LinkedConnection(target.id, target, target.id, await grant_for(db, row, project_id) if row else None)


__all__ = [
    "CODE_SCOPE_NOT_ALLOWED",
    "CODE_USE_DISABLED",
    "USE_KNOWLEDGE",
    "USE_TICKETS",
    "LinkedConnection",
    "LinkedConnectionRefusedError",
    "deviation_refusal",
    "resolve_linked",
]
