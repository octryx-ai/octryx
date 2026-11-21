"""Reading the open ServiceNow records of an intake through the Workspace's ServiceNow connection.

The connection is the Workspace's ``servicenow`` tool entry (over the global one, its credential unit never
mixed, as the Jira intake resolves Jira), and its credential and endpoint style are its own:

- **Table API** (``servicenow_api_style`` ``table``): ``GET /api/now/table/<table>`` with display values,
  ``sysparm_query`` = the intake's encoded query (default ``active=true``) ``^ORDERBYDESCnumber`` — newest
  first, so a bounded listing keeps the recent records — paged by ``sysparm_offset``. At most ``max_items``
  records per table; one more is read to know whether the listing is complete.
- **Scripted REST** (``scripted``): the configured path of the table. The endpoint's order is its own (often
  oldest first) and it cannot filter, so the whole listing is paged (up to :data:`MAX_SCANNED` records per
  table) and split client-side: closed records (``excluded_states``) never count against ``max_items``, and of
  the open ones the newest ``max_items`` (by number) are kept. Open records are never lost to closed ones; a
  listing with more open records than ``max_items``, or cut by the scan bound, is incomplete.

Records are normalised (``servicenow_scripted.normalize_record``) with their ``nav_to`` link. The client never
follows a redirect; failures are closed codes, never a body.

**Record limit.** The effective limit (:func:`effective_limit`) is the connector's
``servicenow_assignment_groups``/``servicenow_services`` (``servicenow_filter_mode``), each list narrowed by the
intake's ``assignment_groups``/``services``; an override outside the connector's limit is refused
(``servicenow_assignment_groups_not_allowed``, for either list), never widened. With a limit, the Table API query
gets its condition and display values *and* values are read so every record is re-checked; a Scripted REST
listing is filtered client-side while paging.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...oidc_client_credentials import OidcTokenError
from ...outbound_egress import CONNECTION_SERVICENOW, egress_transport
from ...servicenow_auth import ServiceNowAuth, resolve_servicenow_auth
from ...servicenow_record_limit import FIELDS, RecordLimit, RecordLimitError, narrowed, record_in_limit
from ...servicenow_record_query import with_clause
from ...servicenow_scripted import (
    MAX_PAGE_SIZE,
    ScriptedApi,
    ScriptedEndpointError,
    normalize_record,
    parse_page,
    scripted_api,
)
from ...servicenow_scripted_fetch import fetch_matching_records
from ..intake.connections import default_connection_config
from .config import is_closed

CODE_NOT_CONFIGURED = "servicenow_connection_not_configured"
CODE_CONNECTION_UNAVAILABLE = "intake_connection_unavailable"
CODE_TABLE_NOT_CONFIGURED = "servicenow_endpoint_not_configured"
CODE_GROUPS_NOT_ALLOWED = "servicenow_assignment_groups_not_allowed"
# The intake's connection refuses it (``named_connections/linked_use.py``).
CONNECTION_REFUSAL_CODES = ("connection_disabled", "connection_not_available", "connection_use_disabled",
                            "connection_ambiguous", "scope_not_allowed")
DEFAULT_TABLE_QUERY = "active=true"
MAX_SCANNED = 5000
NEWEST_FIRST = "ORDERBYDESCnumber"


@dataclass(frozen=True, slots=True)
class Listing:
    records: dict[str, list[dict[str, Any]]]  # table -> normalised records
    complete: bool
    base_url: str
    instance: str
    limit: RecordLimit | None = None


class IntakeSourceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None, field: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.http_status = http_status
        self.field = field  # the refused intake setting, for a limit override


async def connector_config(db: AsyncSession, project_id: str | None) -> dict[str, Any]:
    """The Workspace's default ``servicenow`` entry (its own unit, else the global one)."""
    return await default_connection_config(db, project_id, "servicenow")


def effective_limit(config: Mapping[str, Any], intake: Mapping[str, Any]) -> RecordLimit | None:
    """The connector's limit narrowed by the intake's lists; raises :class:`IntakeSourceError` if it would widen."""
    try:
        return narrowed(config, {spec.intake_field: list(intake.get(spec.intake_field) or []) for spec in FIELDS})
    except RecordLimitError as error:
        raise IntakeSourceError(CODE_GROUPS_NOT_ALLOWED, str(error), field=error.field) from None


async def table_records(
    client: httpx.AsyncClient, base_url: str, table: str, query: str | None, limit: int, headers: dict[str, str],
    scope: RecordLimit | None = None, fields: str | None = None,
) -> list[dict[str, Any]]:
    """Up to ``limit`` records of ``table`` inside ``scope``, newest first (``ORDERBYDESCnumber``); every field
    unless ``fields`` names them."""
    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < limit:
        size = min(MAX_PAGE_SIZE, limit - len(records))
        response = await client.get(
            f"{base_url}/api/now/table/{table}",
            params={"sysparm_query": "^".join(part for part in (with_clause(query, scope), NEWEST_FIRST) if part),
                    "sysparm_display_value": "all" if scope is not None else "true",
                    "sysparm_exclude_reference_link": "true", "sysparm_limit": size, "sysparm_offset": offset,
                    **({"sysparm_fields": fields} if fields else {})},
            headers=headers,
        )
        if response.status_code != 200:
            raise ScriptedEndpointError("servicenow_endpoint_http_status", http_status=response.status_code)
        page = parse_page(response.json() if response.content else None, table).records
        offset += len(page)
        # The server-side condition is re-checked: an instance may ignore a condition it cannot apply.
        records.extend(record for record in page[:size] if record_in_limit(record, scope))
        if len(page) < size:
            break
    return records


@dataclass(frozen=True, slots=True)
class Endpoint:
    """The Workspace's ServiceNow endpoint: base URL, request headers, credential and the Scripted REST paths
    (``None`` on the Table API)."""

    base_url: str
    headers: dict[str, str]
    credential: ServiceNowAuth
    api: ScriptedApi | None


def endpoint(config: Mapping[str, Any]) -> Endpoint:
    """The configured endpoint; raises :class:`IntakeSourceError` (``servicenow_connection_not_configured``)."""
    base_url = str(config.get("servicenow_url") or "").strip().rstrip("/")
    credential = resolve_servicenow_auth(config)
    if not base_url or credential is None:
        raise IntakeSourceError(CODE_NOT_CONFIGURED, "the Workspace has no complete ServiceNow connection")
    try:
        api = scripted_api(config)
    except ScriptedEndpointError:
        raise IntakeSourceError(CODE_NOT_CONFIGURED, "the ServiceNow endpoint configuration is invalid") from None
    return Endpoint(base_url=base_url, headers={"Accept": "application/json", **credential.headers()},
                    credential=credential, api=api)


@asynccontextmanager
async def reading(target: Endpoint) -> AsyncIterator[httpx.AsyncClient]:
    """A client for ``target`` (egress-bound, no redirects); endpoint and token failures become closed
    :class:`IntakeSourceError` codes."""
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, transport=egress_transport(CONNECTION_SERVICENOW),
            auth=target.credential.http_auth(),
        ) as client:
            yield client
    except (ScriptedEndpointError, OidcTokenError) as error:
        raise IntakeSourceError(error.code, str(error), http_status=getattr(error, "http_status", None)) from None
    except httpx.HTTPError:
        raise IntakeSourceError("servicenow_endpoint_unreachable", "ServiceNow could not be reached") from None


async def list_open_records(config: Mapping[str, Any], intake: Mapping[str, Any]) -> Listing:
    """The records of every configured table, normalised; raises :class:`IntakeSourceError`."""
    target = endpoint(config)
    base_url, api = target.base_url, target.api
    scope = effective_limit(config, intake)
    limit = int(intake["max_items"])
    listed: dict[str, list[dict[str, Any]]] = {}
    complete = True
    async with reading(target) as client:
        for table in intake["tables"]:
            if api is None:
                query = intake.get("sysparm_query") or DEFAULT_TABLE_QUERY
                raw = await table_records(client, base_url, table, query, limit + 1, target.headers, scope)
                complete = complete and len(raw) <= limit
                listed[table] = [normalize_record(with_ref_ids(record), table, base_url) for record in raw[:limit]]
                continue
            path = api.paths.get(table)
            if not path:
                raise IntakeSourceError(CODE_TABLE_NOT_CONFIGURED, f"no Scripted REST path for {table}")
            raw, listed_all = await fetch_matching_records(
                client, base_url, path, table, limit=MAX_SCANNED, page_size=api.page_size, headers=target.headers,
                keep=lambda record: record_in_limit(record, scope), max_scanned=MAX_SCANNED,
            )
            records, all_open = _open_first(
                [normalize_record(with_ref_ids(record), table, base_url) for record in raw], intake, limit)
            complete = complete and listed_all and all_open
            listed[table] = records
    return Listing(records=listed, complete=complete, base_url=base_url, instance=httpx.URL(base_url).host,
                   limit=scope)


def _open_first(records: list[dict[str, Any]], intake: Mapping[str, Any], limit: int,
                ) -> tuple[list[dict[str, Any]], bool]:
    """The newest ``limit`` open records (by number, descending) followed by every closed one, and whether no
    open record was cut. Closed records never count against ``limit``: they only close existing items."""
    open_records = [record for record in records if not is_closed(record.get("state"), intake)]
    closed = [record for record in records if is_closed(record.get("state"), intake)]
    newest = sorted(open_records, key=lambda record: str(record.get("number") or ""), reverse=True)
    return newest[:limit] + closed, len(newest) <= limit


def with_ref_ids(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """The record plus the ``sys_id`` of its group and service when the answer carries them (``display_value=all``
    or an object): ``assignment_group_sys_id``, ``service_sys_id``."""
    extra = {}
    for key, field in (("assignment_group_sys_id", "assignment_group"), ("service_sys_id", "business_service"),
                       ("service_sys_id", "service")):
        reference = record.get(field)
        value = reference.get("value") if isinstance(reference, Mapping) else None
        if isinstance(value, str) and value and key not in extra:
            extra[key] = value
    return {**record, **extra} if extra else record


def source_error(error: IntakeSourceError) -> HTTPException:
    coded = (CODE_NOT_CONFIGURED, CODE_TABLE_NOT_CONFIGURED, CODE_GROUPS_NOT_ALLOWED, CODE_CONNECTION_UNAVAILABLE,
             *CONNECTION_REFUSAL_CODES)
    # ``refusal``: a source's own configuration refusal (Custom REST) is a 409 like the coded ones.
    status = 409 if error.code in coded or getattr(error, "refusal", False) else 502
    return HTTPException(status_code=status, detail={"state": "failed", "code": error.code, "message": str(error)})


__all__ = ["Endpoint", "IntakeSourceError", "Listing", "connector_config", "effective_limit", "endpoint",
           "list_open_records", "reading", "source_error", "table_records", "with_ref_ids"]
