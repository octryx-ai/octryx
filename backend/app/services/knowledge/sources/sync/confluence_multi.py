"""A Confluence connector whose spaces are served by different named connections.

Each listing unit (a whole space, then each page tree, in the scope's order) is read by its own
:class:`ConfluenceConnector` over that unit alone, built on the connection that serves the unit's space
(``scope_connections.py``). The cursor token is the single connector's: ``"<unit index>:<position>"``,
so a run resumes at the same unit and position whichever connector shape wrote it, and a scope whose
bindings change keeps its pass.

An item is fetched, and its restriction expanded, by the unit that listed it in this run; an item this
run never listed is a contract violation, never read with a guessed connection. Per unit, the space,
the connection name and id (never a URL or a credential) and the unit's listed items are logged and reported
(``scope_of`` / ``scope_connections`` feed the run report's ``scopes``).
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_CONFLUENCE
from .confluence import ConfluenceConnector
from .confluence_links import _parse_token
from .connections import SourceConnection
from .contract import (
    REASON_SOURCE_CONTRACT_VIOLATION,
    AclExpansion,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .cursor import MAX_TOKEN_CHARS

logger = logging.getLogger(__name__)


class MultiConnectionConfluenceConnector:
    kind = CONNECTOR_KIND_CONFLUENCE
    requires_parser = True

    def __init__(
        self,
        units: tuple[tuple[str, tuple[str, str], SourceConnection, dict | None], ...],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """``units``: ``(space key, (connection name, ref), connection, page tree or None)`` in token order."""
        self._units = tuple(
            (
                space,
                label,
                ConfluenceConnector(
                    connection,
                    spaces=() if tree is not None else (space,),
                    page_trees=(tree,) if tree is not None else (),
                    transport=transport,
                ),
            )
            for space, label, connection, tree in units
        )
        self._listed_by: dict[str, int] = {}
        self._announced: set[int] = set()

    def scope_connections(self) -> dict[str, tuple[str, str]]:
        """``{space: (connection name, connection ref)}``: the account of each space, by name and id."""
        return {space: label for space, label, _ in self._units}

    def scope_of(self, external_id: str) -> str | None:
        index = self._listed_by.get(external_id)
        return None if index is None else self._units[index][0]

    def _announce(self, index: int) -> None:
        if index not in self._announced:
            self._announced.add(index)
            space, (name, ref), _ = self._units[index]
            logger.info("Confluence source sync unit: space=%s connection=%s id=%s", space, name, ref)

    async def _page(self, token: str | None, limit: int, since: datetime | None) -> ListingPage:
        index, position = _parse_token(token)
        if index >= len(self._units):
            return ListingPage(items=(), next_token=None)
        self._announce(index)
        unit = self._units[index][2]
        inner = f"0:{position}"
        if since is None:
            page = await unit.list_items(inner, limit=limit)
        else:
            page = await unit.list_changed_items(inner, since=since, limit=limit)
        for item in page.items:
            self._listed_by[item.external_id] = index
        if page.next_token is not None:
            _, inner_position = _parse_token(page.next_token)
            next_token = f"{index}:{inner_position}"
            if len(next_token) > MAX_TOKEN_CHARS:
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        else:
            next_token = f"{index + 1}:0" if index + 1 < len(self._units) else None
        return ListingPage(items=page.items, next_token=next_token, deleted=page.deleted, skipped=page.skipped)

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        return await self._page(token, limit, None)

    async def list_changed_items(self, token: str | None, *, since: datetime, limit: int) -> ListingPage:
        return await self._page(token, limit, since)

    def _unit_of(self, item: SourceItem) -> ConfluenceConnector:
        index = self._listed_by.get(item.external_id)
        if index is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return self._units[index][2]

    async def expand_item_acl(self, item: SourceItem) -> AclExpansion | None:
        return await self._unit_of(item).expand_acl(item.acl)

    async def fetch(self, item: SourceItem) -> ItemContent:
        return await self._unit_of(item).fetch(item)


def multi_connection_connector(
    scope: dict, scoped, *, transport: httpx.AsyncBaseTransport | None = None
) -> MultiConnectionConfluenceConnector:
    """The connector over ``scope`` (whole spaces, then page trees) with each unit on its space's connection.

    ``scoped`` is the :class:`~.scope_connections.ScopeConnections` of the scope (connections by id).
    """
    whole = [(str(space), None) for space in scope.get("spaces") or ()]
    trees = [(str(tree.get("space_key") or ""), dict(tree)) for tree in scope.get("page_trees") or ()]
    units = []
    for space, tree in (*whole, *trees):
        ref = scoped.by_key[space]
        units.append((space, (scoped.names.get(ref, ref), ref), scoped.connections[ref], tree))
    return MultiConnectionConfluenceConnector(tuple(units), transport=transport)


__all__ = ["MultiConnectionConfluenceConnector", "multi_connection_connector"]
