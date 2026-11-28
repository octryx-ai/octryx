"""A use that names its connection by id: an intake (``work_item_sync_configs.connection_id``) or a Knowledge source
(``knowledge_source_connectors.connection_id``)."""

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
    def __init__(self, code: str, scopes: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.scopes = list(scopes or [])

    def detail(self) -> dict:
        detail = {"state": "needs_configuration", "code": self.code, "reason": self.code}
        return {**detail, "scopes": self.scopes} if self.scopes else detail


@dataclass(frozen=True, slots=True)
class LinkedConnection:
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
