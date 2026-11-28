"""Custom REST as a Knowledge source on the Source Sync contract (``SourceConnector``). Synced content is untrusted."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .....models import RestApiDefinition, RestApiOperation
from .....models.project.knowledge_source_sync import CONNECTOR_KIND_CUSTOM_REST
from ....rest_connector.authorization import AppliedScope, NotGrantedError, ScopeError, matching_grants, resolve_scope
from ....rest_connector.response import locate_records
from ....secure_work.custom_rest.listing import (
    CODE_OPERATION_UNAVAILABLE,
    IntakeCallContext,
    call_read,
    read_page,
)
from ....secure_work.servicenow.source import IntakeSourceError
from .contract import (
    REASON_EGRESS_REFUSED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    REASON_SOURCE_RATE_LIMITED,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
    AclExpansion,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .cursor import MAX_TOKEN_CHARS
from .rest_acl import admitted_roles, expand_roles, facet_for, roles_of
from .rest_config import SANDBOXED_MEDIA, VISIBILITY_WORKSPACE
from .rest_connection import RestSourceConnection
from .rest_render import RecordHeader, item_content, record_header
from .stored_types import RestListingFacts

REASON_DETAIL_OUT_OF_SCOPE = "custom_rest_detail_out_of_scope"
REASON_CURSOR_TOO_LONG = "custom_rest_cursor_too_long"
_HTTP_REASONS = {401: REASON_SOURCE_UNAUTHORIZED, 403: REASON_SOURCE_UNAUTHORIZED, 404: REASON_SOURCE_NOT_FOUND,
                 429: REASON_SOURCE_RATE_LIMITED}


def source_reason(error: IntakeSourceError) -> str:
    # Never the message: it may quote the API.
    if error.code == "custom_rest_egress_refused":
        return REASON_EGRESS_REFUSED
    if error.code == "custom_rest_http_error":
        return _HTTP_REASONS.get(error.http_status or 0, REASON_SOURCE_UNAVAILABLE)
    if error.code == "custom_rest_request_failed":
        return REASON_SOURCE_UNAVAILABLE
    return error.code[:40]


def _token(raw: str | None) -> tuple[int, str | None]:
    if raw is None:
        return 0, None
    skip, _, cursor = raw.partition(":")
    if not skip.isdigit():
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return int(skip), cursor or None


def _applied(operation: Any, role: str, project_id: str, arguments: Mapping[str, Any]) -> AppliedScope:
    try:
        return resolve_scope(matching_grants(operation, frozenset({role.lower()}), project_id), dict(arguments))
    except NotGrantedError:
        raise ConnectorError("custom_rest_not_granted") from None
    except ScopeError:
        raise ConnectorError("custom_rest_scope_violation") from None


class RestKnowledgeConnector:
    kind = CONNECTOR_KIND_CUSTOM_REST

    def __init__(self, connection: RestSourceConnection, *, scope: Mapping[str, Any], db: AsyncSession,
                 project_id: str, actor_id: str | None) -> None:
        self._connection = connection
        # Ids, not the resolved rows: the runner rolls back after a refused ingestion, which expires every loaded row,
        # and an expired row must be reloaded with an awaited ``get`` (``_rows``), never by a lazy attribute access.
        self._row_ids = (connection.definition.id, connection.operation.id,
                         connection.detail.id if connection.detail is not None else None)
        self._fallback_title = connection.definition.name or connection.definition.key
        self._db = db
        self._project_id = project_id
        self._mapping = dict(scope.get("mapping") or {})
        self._arguments = dict(scope.get("arguments") or {})
        self._media_type = str(scope.get("media_type"))
        self._workspace_visible = scope.get("visibility") == VISIBILITY_WORKSPACE
        self._context = IntakeCallContext(user_id=actor_id, project_id=project_id, db=db, acting_role=connection.role)
        self.requires_parser = self._media_type in SANDBOXED_MEDIA
        # external id -> (header, listed record) of this run's listing pages, for ``fetch``.
        self._listed: dict[str, tuple[RecordHeader, Mapping[str, Any]]] = {}
        self._expansions: dict[frozenset[str], AclExpansion] = {}
        self._list_scope: AppliedScope | None = None
        self._detail_roles: frozenset[str] | None = None
        self.listing_facts: RestListingFacts = {"role": connection.role, "pages": 0, "dropped_out_of_scope": 0}
        since = scope.get("updated_since_param")
        if since:
            # Only a source with a change parameter offers the accelerator (``incremental.accelerator_due``).
            self._since_param = str(since)
            self.list_changed_items = self._list_changed_items

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        return await self._list(token, limit=limit, arguments=self._arguments)

    async def _list_changed_items(self, token: str | None, *, since: datetime, limit: int) -> ListingPage:
        instant = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return await self._list(token, limit=limit, arguments={**self._arguments, self._since_param: instant})

    async def _rows(self) -> tuple[Any, Any, Any]:
        definition_id, operation_id, detail_id = self._row_ids
        definition = await self._db.get(RestApiDefinition, definition_id)
        operation = await self._db.get(RestApiOperation, operation_id)
        detail = await self._db.get(RestApiOperation, detail_id) if detail_id else None
        if definition is None or operation is None or (detail_id and detail is None):
            raise ConnectorError(CODE_OPERATION_UNAVAILABLE)  # removed during the run
        return definition, operation, detail

    async def _list(self, token: str | None, *, limit: int, arguments: Mapping[str, Any]) -> ListingPage:
        skip, cursor = _token(token)
        definition, operation, _detail = await self._rows()
        try:
            page = await read_page(self._db, definition=definition, operation=operation,
                                   context=self._context, arguments=arguments, cursor=cursor)
        except IntakeSourceError as error:
            raise ConnectorError(source_reason(error)) from None
        self.listing_facts["pages"] += 1
        if skip == 0:
            self.listing_facts["dropped_out_of_scope"] += page.dropped  # a re-read slice counts its page once
        records = page.records[skip:skip + limit]
        if skip + limit < len(page.records):
            next_token: str | None = f"{skip + limit}:{cursor or ''}"
        else:
            next_token = f"0:{page.next_cursor}" if page.next_cursor else None
        if next_token is not None and len(next_token) > MAX_TOKEN_CHARS:
            # The stored cursor is bounded (``cursor.py``); a longer next URL ends the run with a reason, never cut.
            raise ConnectorError(REASON_CURSOR_TOO_LONG)
        items: list[SourceItem] = []
        skipped: list[tuple[str, str]] = []
        for position, record in enumerate(records, start=skip):
            header = record_header(record, self._mapping, self._fallback_title)
            if isinstance(header, str):
                skipped.append((f"record-{position}", header))
                continue
            self._listed[header.external_id] = (header, record)
            items.append(SourceItem(header.external_id, header.title, header.source_url, header.version_marker,
                                    self._facet(record, operation, _detail), source_changed_at=header.changed_at))
        return ListingPage(items=tuple(items), next_token=next_token, skipped=tuple(skipped))

    def _facet(self, record: Mapping[str, Any], operation: Any, detail: Any) -> AclFacet:
        if self._workspace_visible:
            return AclFacet.scope()
        role = self._connection.role
        if self._list_scope is None:
            self._list_scope = _applied(operation, role, self._project_id, self._arguments)
        roles = admitted_roles(operation, self._list_scope, self._project_id, record)
        if detail is not None:
            if self._detail_roles is None:
                applied = _applied(detail, role, self._project_id, {})
                self._detail_roles = admitted_roles(detail, applied, self._project_id, None)
            roles &= self._detail_roles
        return facet_for(roles)

    async def fetch(self, item: SourceItem) -> ItemContent:
        listed = self._listed.get(item.external_id)
        if listed is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        header, record = listed
        if self._row_ids[2] is not None:
            record = await self._detail(header)
        return ItemContent(data=item_content(record, self._mapping, self._media_type, header.title),
                           media_type=self._media_type if self._media_type != "application/json" else "text/markdown")

    async def _detail(self, header: RecordHeader) -> Mapping[str, Any]:
        definition, _operation, detail = await self._rows()
        try:
            result = await call_read(self._db, definition=definition, operation=detail, context=self._context,
                                     arguments={self._connection.detail_param: header.original_id})
        except IntakeSourceError as error:
            raise ConnectorError(source_reason(error)) from None
        data = result.get("data")
        if data is None and result.get("dropped_out_of_scope"):
            raise ConnectorError(REASON_DETAIL_OUT_OF_SCOPE)  # the role's result filter refused this record
        if detail.records_path or isinstance(data, list):
            # One record wrapped in a list (or under the operation's own records path); any other count is no detail.
            found, _path = locate_records(data, detail.records_path)
            data = found[0] if found is not None and len(found) == 1 else None
        if not isinstance(data, Mapping):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return data

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        roles = roles_of(acl)
        if roles is None:
            return None
        if roles not in self._expansions:
            self._expansions[roles] = await expand_roles(self._db, self._project_id, roles)
        return self._expansions[roles]


__all__ = ["REASON_DETAIL_OUT_OF_SCOPE", "RestKnowledgeConnector", "source_reason"]
