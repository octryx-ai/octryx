"""ServiceNow incidents and changes from the instance's Scripted REST endpoints, on the Source Sync contract."""

from __future__ import annotations

import hashlib
import json
import re

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_SERVICENOW
from ....servicenow_record_limit import record_in_limit
from ....servicenow_scripted import ScriptedEndpointError, parse_page, record_link
from .contract import (
    REASON_SCOPE_NOT_ALLOWED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .http import SourceReader
from .servicenow import MAX_TITLE_CHARS, record_acl
from .servicenow_connection import ServiceNowConnection
from .servicenow_render import item_title, render_record
from .source_dates import source_date

_SYS_ID = re.compile(r"^[0-9a-f]{32}$")


def _token(token: str | None) -> tuple[int, int]:
    if token is None:
        return 0, 0
    try:
        index, offset = (int(part) for part in token.split(":", 1))
    except ValueError:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    if index < 0 or offset < 0:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return index, offset


def _marker(record: dict) -> str:
    updated, mod_count = record.get("sys_updated_on"), record.get("sys_mod_count")
    if isinstance(updated, str) and updated:
        return f"{mod_count}@{updated}" if isinstance(mod_count, str | int) else updated
    return "sha256:" + hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:32]


def scripted_acl(record: dict) -> AclFacet:
    return record_acl(record) if "sys_domain" in record else AclFacet.scope()


class ServiceNowScriptedConnector:
    kind = CONNECTOR_KIND_SERVICENOW
    requires_parser = False

    def __init__(
        self,
        connection: ServiceNowConnection,
        *,
        knowledge_bases: tuple[str, ...] = (),
        tables: tuple[str, ...] = (),
        article_filter: str | None = None,
        record_filter: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        api = connection.api
        if api is None or knowledge_bases or article_filter or record_filter:
            raise ConnectorError(REASON_SCOPE_NOT_ALLOWED)
        if any(table not in api.paths for table in tables):
            raise ConnectorError(REASON_SCOPE_NOT_ALLOWED)  # a table without a configured endpoint
        self._connection = connection
        self._transport = transport
        self._page_size = api.page_size
        self._targets: list[tuple[str, str]] = [(table, api.paths[table]) for table in tables]
        self._reader: SourceReader | None = None
        # sys_id -> (table, record) of the listing pages of this run; ``fetch`` renders from it.
        self._listed: dict[str, tuple[str, dict]] = {}

    async def _page(self, path: str, table: str, *, limit: int, offset: int):
        if self._reader is None:
            auth = await self._connection.request_auth(transport=self._transport)
            self._reader = SourceReader(auth, transport=self._transport)
        payload = await self._reader.get_json(path, {"sysparm_limit": limit, "sysparm_offset": offset})
        try:
            return parse_page(payload, table)
        except ScriptedEndpointError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None

    def _item(self, table: str, record: dict) -> SourceItem:
        sys_id = record.get("sys_id")
        if not isinstance(sys_id, str) or not _SYS_ID.fullmatch(sys_id):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        self._listed[sys_id] = (table, record)
        title = item_title(record, f"ServiceNow {table} {sys_id}")[:MAX_TITLE_CHARS]
        link = record_link(self._connection.base_url, table, sys_id)
        return SourceItem(sys_id, title, link, _marker(record), scripted_acl(record),
                          source_changed_at=source_date(record.get("sys_updated_on")))

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        index, offset = _token(token)
        if index >= len(self._targets):
            return ListingPage(items=(), next_token=None)
        table, path = self._targets[index]
        size = max(1, min(limit, self._page_size))
        page = await self._page(path, table, limit=size, offset=offset)
        if len(page.records) > size:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        limit_of = self._connection.limit
        items = tuple(self._item(table, record) for record in page.records
                      if not isinstance(record, dict) or record_in_limit(record, limit_of))
        reached = offset + len(page.records)
        if len(page.records) == size and (page.total is None or reached < page.total):
            next_token = f"{index}:{reached}"
        else:
            next_token = f"{index + 1}:0" if index + 1 < len(self._targets) else None
        return ListingPage(items=items, next_token=next_token)

    async def fetch(self, item: SourceItem) -> ItemContent:
        listed = self._listed.get(item.external_id)
        if listed is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        table, record = listed
        return ItemContent(data=render_record(table, record, item.title), media_type="text/markdown")


__all__ = ["ServiceNowScriptedConnector", "scripted_acl"]
