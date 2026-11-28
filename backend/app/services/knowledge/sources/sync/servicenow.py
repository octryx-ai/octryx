"""ServiceNow knowledge articles and records, on the Source Sync contract."""

from __future__ import annotations

import re

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_SERVICENOW
from ....servicenow_record_limit import CHECK_FIELDS, record_in_limit
from ....servicenow_record_query import with_clause
from .contract import (
    REASON_SOURCE_CONTRACT_VIOLATION,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .http import SourceReader
from .servicenow_connection import ServiceNowConnection
from .servicenow_render import ARTICLE_FIELDS, RECORD_FIELDS, item_title, render_article, render_record
from .servicenow_scope import KNOWLEDGE_TABLE, article_query, record_query
from .source_dates import source_date

MAX_TITLE_CHARS = 300
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_LIST_COMMON = "sys_id,number,short_description,sys_updated_on,sys_mod_count"
_ARTICLE_LIST_FIELDS = f"{_LIST_COMMON},can_read_user_criteria,cannot_read_user_criteria,roles"
_RECORD_LIST_FIELDS = f"{_LIST_COMMON},sys_domain"
_LIMIT_LIST_FIELDS = ",".join((_RECORD_LIST_FIELDS, *CHECK_FIELDS))
GLOBAL_DOMAIN = "global"


def _parse_token(token: str | None) -> tuple[int, int]:
    if token is None:
        return 0, 0
    try:
        index, offset = (int(part) for part in token.split(":", 1))
    except ValueError:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    if index < 0 or offset < 0:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return index, offset


def _ids(value: object) -> tuple[str, ...] | None:
    if value is None or not isinstance(value, str):
        return None
    return tuple(part.strip() for part in value.split(",") if part.strip())


def article_acl(record: dict) -> AclFacet:
    can_read, cannot_read = _ids(record.get("can_read_user_criteria")), _ids(record.get("cannot_read_user_criteria"))
    if can_read is None or cannot_read is None:
        return AclFacet.unknown()
    if can_read:
        return AclFacet.restricted("user_criteria", tuple(f"user_criteria:{item}" for item in can_read))
    if cannot_read:
        return AclFacet.restricted("user_criteria_exclusion", tuple(f"user_criteria:{item}" for item in cannot_read))
    roles = record.get("roles")
    if isinstance(roles, str) and roles.strip():
        return AclFacet.restricted("roles", tuple(f"role:{item}" for item in _ids(roles) or ()))
    return AclFacet.scope()


def record_acl(record: dict) -> AclFacet:
    domain = record.get("sys_domain")
    if isinstance(domain, dict):
        domain = domain.get("value")
    if not isinstance(domain, str) or not domain.strip():
        return AclFacet.unknown()
    if domain.strip() == GLOBAL_DOMAIN:
        return AclFacet.scope()
    return AclFacet.restricted("domain_separation", (f"domain:{domain.strip()}",))


class ServiceNowConnector:
    kind = CONNECTOR_KIND_SERVICENOW

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
        self._connection = connection
        self._transport = transport
        self._reader: SourceReader | None = None
        # (table, encoded query) per target, in listing order.
        self._targets: list[tuple[str, str]] = []
        if knowledge_bases:
            self._targets.append((KNOWLEDGE_TABLE, article_query(tuple(knowledge_bases), article_filter)))
        self._limit = connection.limit
        self._targets.extend((table, with_clause(record_query(record_filter), self._limit)) for table in tables)
        # HTML articles go through the parser sandbox; a records-only connector needs none.
        self.requires_parser = bool(knowledge_bases)
        # sys_id -> table of the listing pages of this run; ``fetch`` reads from the right table.
        self._listed: dict[str, str] = {}

    async def _get(self, path: str, params: dict) -> dict:
        if self._reader is None:
            auth = await self._connection.request_auth(transport=self._transport)
            self._reader = SourceReader(auth, transport=self._transport)
        return await self._reader.get_json(path, params)

    def _link(self, table: str, sys_id: str) -> str:
        base = self._connection.base_url
        if table == KNOWLEDGE_TABLE:
            return f"{base}/kb_view.do?sys_kb_id={sys_id}"
        return f"{base}/{table}.do?sys_id={sys_id}"

    def _header(self, table: str, record: object) -> SourceItem:
        if not isinstance(record, dict):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        sys_id = str(record.get("sys_id") or "")
        updated, mod_count = record.get("sys_updated_on"), record.get("sys_mod_count")
        if not _SYS_ID.fullmatch(sys_id) or not isinstance(updated, str) or not updated:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        self._listed[sys_id] = table
        acl = article_acl(record) if table == KNOWLEDGE_TABLE else record_acl(record)
        title = item_title(record, f"ServiceNow {table} {sys_id}")[:MAX_TITLE_CHARS]
        marker = f"{mod_count}@{updated}" if isinstance(mod_count, str | int) else updated
        return SourceItem(sys_id, title, self._link(table, sys_id), marker, acl,
                          source_changed_at=source_date(updated))

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        index, offset = _parse_token(token)
        if index >= len(self._targets):
            return ListingPage(items=(), next_token=None)
        table, query = self._targets[index]
        fields = _ARTICLE_LIST_FIELDS if table == KNOWLEDGE_TABLE else (
            _RECORD_LIST_FIELDS if self._limit is None else _LIMIT_LIST_FIELDS)
        payload = await self._get(
            f"/api/now/table/{table}",
            {
                "sysparm_query": query,
                "sysparm_fields": fields,
                "sysparm_limit": limit,
                "sysparm_offset": offset,
                "sysparm_display_value": "false",
                "sysparm_exclude_reference_link": "true",
                "sysparm_no_count": "true",
            },
        )
        results = payload.get("result")
        if not isinstance(results, list) or len(results) > limit:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        kept = None if table == KNOWLEDGE_TABLE else self._limit  # the server-side condition is re-checked
        listed = [record for record in results if not isinstance(record, dict) or record_in_limit(record, kept)]
        items = tuple(self._header(table, record) for record in listed)
        if len(results) == limit:
            next_token = f"{index}:{offset + len(results)}"
        else:
            next_token = f"{index + 1}:0" if index + 1 < len(self._targets) else None
        return ListingPage(items=items, next_token=next_token)

    async def fetch(self, item: SourceItem) -> ItemContent:
        table = self._listed.get(item.external_id)
        if table is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        fields = ARTICLE_FIELDS if table == KNOWLEDGE_TABLE else RECORD_FIELDS
        # Articles keep their raw HTML; records are rendered from display values.
        display = "false" if table == KNOWLEDGE_TABLE else "true"
        payload = await self._get(
            f"/api/now/table/{table}/{item.external_id}",
            {"sysparm_fields": fields, "sysparm_display_value": display, "sysparm_exclude_reference_link": "true"},
        )
        record = payload.get("result")
        if not isinstance(record, dict) or record.get("sys_id") != item.external_id:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        if table == KNOWLEDGE_TABLE:
            data, media_type = render_article(record, item.title)
            return ItemContent(data=data, media_type=media_type)
        return ItemContent(data=render_record(table, record, item.title), media_type="text/markdown")


__all__ = ["ServiceNowConnector", "article_acl", "record_acl"]
