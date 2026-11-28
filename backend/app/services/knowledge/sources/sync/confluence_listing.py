"""The listing side of the Confluence connector: headers, paging, page allowlist and read ACLs."""

from __future__ import annotations

import dataclasses
from datetime import datetime

from ....confluence_pages.rules import page_decision
from .confluence_links import (
    _LIST_EXPAND,
    CQL_TIME_FORMAT,
    MAX_TITLE_CHARS,
    _parse_token,
    _principals,
    _with_limit,
    canonical_page_url,
)
from .confluence_scope import tree_cql
from .contract import REASON_SOURCE_CONTRACT_VIOLATION, AclFacet, ConnectorError, ListingPage, SourceItem
from .cursor import MAX_TOKEN_CHARS
from .http import SourceReader
from .source_dates import source_date


class ConfluenceListing:
    _reader: SourceReader
    _spaces: tuple[str, ...]
    _trees: tuple[dict[str, str], ...]
    _units: int
    _restrictions: dict[str, tuple[str, ...]]

    async def _own_restriction(self, page_id: str) -> tuple[str, ...] | None:
        if page_id in self._restrictions:
            return self._restrictions[page_id]
        try:
            payload = await self._reader.get_json(f"/rest/api/content/{page_id}/restriction/byOperation/read")
        except ConnectorError:
            return None
        principals = _principals(payload)
        if principals is not None:
            self._restrictions[page_id] = principals
        return principals

    async def _acl(self, page_id: str, own: tuple[str, ...] | None, ancestors: list[str]) -> AclFacet:
        if own is None:
            return AclFacet.unknown()
        if own:
            return AclFacet.restricted("page_restriction", own)
        for ancestor_id in ancestors:
            inherited = await self._own_restriction(ancestor_id)
            if inherited is None:
                return AclFacet.unknown()
            if inherited:
                return AclFacet.restricted("ancestor_restriction", inherited)
        return AclFacet.scope()

    def _title_and_link(self, result: dict, page_id: str, response_base: object) -> tuple[str, str]:
        title = " ".join(str(result.get("title") or "").split())[:MAX_TITLE_CHARS] or f"Confluence page {page_id}"
        links = result.get("_links") if isinstance(result.get("_links"), dict) else {}
        link = canonical_page_url(self._reader.base_url, page_id, webui=links.get("webui"), response_base=response_base)
        if link is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return title, link

    def _header(
        self, result: dict, response_base: object = None
    ) -> tuple[SourceItem, tuple[str, ...] | None, list[str]]:
        page_id = str(result.get("id") or "").strip()
        version_info = result.get("version")
        version = version_info.get("number") if isinstance(version_info, dict) else None
        if not page_id.isdigit() or type(version) is not int:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        title, link = self._title_and_link(result, page_id, response_base)
        own = _principals((result.get("restrictions") or {}).get("read"))
        ancestors = [str(item.get("id")) for item in result.get("ancestors") or [] if isinstance(item, dict)]
        item = SourceItem(page_id, title, link, str(version), AclFacet.unknown(), read_base=self._reader.base_url,
                          source_changed_at=source_date(version_info.get("when")))
        return item, own, ancestors

    def _unit_cql(self, index: int) -> str:
        if index < len(self._spaces):
            # Space keys are validated (``config.py``): letters, digits, ``_`` and a leading ``~`` only.
            return f'space="{self._spaces[index]}" and type=page'
        return tree_cql(self._trees[index - len(self._spaces)])

    async def _search(self, cql: str, position: int, limit: int) -> dict:
        # Ordered by id, so offset paging (``start``) neither skips nor repeats a page between two requests.
        params: dict[str, object] = {"cql": f"{cql} order by id", "limit": limit, "expand": _LIST_EXPAND}
        if position:
            params["start"] = position
        return await self._reader.get_json("/rest/api/content/search", params)

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        index, position = _parse_token(token)
        if index >= self._units:
            return ListingPage(items=(), next_token=None)
        if isinstance(position, str):
            payload = await self._reader.get_link(_with_limit(position, limit))
        elif index >= len(self._spaces):
            payload = await self._search(self._unit_cql(index), position, limit)
        else:
            payload = await self._reader.get_json(
                "/rest/api/content",
                {
                    "spaceKey": self._spaces[index],
                    "type": "page",
                    "status": "current",
                    "start": position,
                    "limit": limit,
                    "expand": _LIST_EXPAND,
                },
            )
        return await self._page(payload, index, limit)

    async def list_changed_items(self, token: str | None, *, since: datetime, limit: int) -> ListingPage:
        index, position = _parse_token(token)
        if index >= self._units:
            return ListingPage(items=(), next_token=None)
        if isinstance(position, str):
            payload = await self._reader.get_link(_with_limit(position, limit))
        else:
            cql = f'{self._unit_cql(index)} and lastmodified >= "{since:{CQL_TIME_FORMAT}}"'
            payload = await self._search(cql, position, limit)
        return await self._page(payload, index, limit)

    async def _page(self, payload: dict, index: int, limit: int) -> ListingPage:
        results = payload.get("results")
        if not isinstance(results, list) or len(results) > limit:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        page_links = payload.get("_links") if isinstance(payload.get("_links"), dict) else {}
        response_base = page_links.get("base")
        headers = [self._header(result, response_base) for result in results if isinstance(result, dict)]
        headers = [header for header in headers if self._page_listed(header[0], header[2], index)]
        for item, own, _ in headers:
            if own is not None:
                self._restrictions[item.external_id] = own
        items = []
        for item, own, ancestors in headers:
            acl = await self._acl(item.external_id, own, ancestors)
            items.append(dataclasses.replace(item, acl=acl))  # every header field kept, the ACL resolved
        next_link = page_links.get("next")
        if results and next_link is not None:
            if type(next_link) is not str or not next_link.startswith("/"):
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
            next_token = f"{index}:{next_link}"
            if len(next_token) > MAX_TOKEN_CHARS:
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        else:
            next_token = f"{index + 1}:0" if index + 1 < self._units else None
        return ListingPage(items=tuple(items), next_token=next_token)

    def _unit_space(self, index: int) -> str:
        if index < len(self._spaces):
            return self._spaces[index]
        return self._trees[index - len(self._spaces)]["space_key"]

    def _page_listed(self, item: SourceItem, ancestors: list[str], index: int) -> bool:
        # A rule change does not modify the page, so the change listing never lists a newly excluded page: the next
        # completed header pass retires it.
        decision = page_decision(
            self._page_rules,
            page_id=item.external_id,
            space_key=self._unit_space(index),
            ancestor_ids=ancestors,
            allowed_spaces=self._allowed_spaces,
        )
        return decision is not False
