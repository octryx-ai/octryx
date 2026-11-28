"""Reading the open ServiceNow records of an intake through the Workspace's ServiceNow connection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...connector_auth.oidc_client_credentials import OidcTokenError
from ...connector_auth.servicenow import ServiceNowAuth, resolve_servicenow_auth
from ...outbound_egress import CONNECTION_SERVICENOW, egress_transport
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
    return await default_connection_config(db, project_id, "servicenow")


def effective_limit(config: Mapping[str, Any], intake: Mapping[str, Any]) -> RecordLimit | None:
    # The intake may only narrow the connector's limit, never widen it.
    try:
        return narrowed(config, {spec.intake_field: list(intake.get(spec.intake_field) or []) for spec in FIELDS})
    except RecordLimitError as error:
        raise IntakeSourceError(CODE_GROUPS_NOT_ALLOWED, str(error), field=error.field) from None


async def table_records(
    client: httpx.AsyncClient, base_url: str, table: str, query: str | None, limit: int, headers: dict[str, str],
    scope: RecordLimit | None = None, fields: str | None = None,
) -> list[dict[str, Any]]:
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
    base_url: str
    headers: dict[str, str]
    credential: ServiceNowAuth
    api: ScriptedApi | None


def endpoint(config: Mapping[str, Any]) -> Endpoint:
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
    # Egress-bound, no redirects.
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
    # Closed records never count against ``limit``: they only close existing items.
    open_records = [record for record in records if not is_closed(record.get("state"), intake)]
    closed = [record for record in records if is_closed(record.get("state"), intake)]
    newest = sorted(open_records, key=lambda record: str(record.get("number") or ""), reverse=True)
    return newest[:limit] + closed, len(newest) <= limit


def with_ref_ids(record: Mapping[str, Any]) -> Mapping[str, Any]:
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
