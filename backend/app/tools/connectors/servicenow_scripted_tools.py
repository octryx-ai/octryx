"""The ServiceNow incident and change tools on the instance's Scripted REST API.

With ``servicenow_api_style=scripted`` the incident and change tools page through the configured paths
(``services/servicenow_scripted.py``) instead of the Table API, and the generic table tools answer the coded
``servicenow_table_api_disabled``: they never fall back to the Table API. A query filter is refused, never
silently dropped. Failures are closed codes; no response body, secret or token is returned.

With the connector's record limit (``servicenow_assignment_groups``/``servicenow_services``,
``services/servicenow_record_limit.py``) the listing keeps only records inside it (client-side: the endpoint
lists what it lists), paging on up to
:data:`MAX_SCANNED_PER_CALL` records to fill the requested limit; ``total`` is then not reported.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.oidc_client_credentials import OidcTokenError
from app.services.outbound_egress import CONNECTION_SERVICENOW, egress_transport
from app.services.servicenow_record_limit import record_in_limit, record_limit
from app.services.servicenow_scripted import (
    CODE_ENDPOINT_NOT_CONFIGURED,
    CODE_QUERY_UNSUPPORTED,
    CODE_TABLE_API_DISABLED,
    MESSAGES,
    ScriptedEndpointError,
    normalize_record,
    scripted_api,
)
from app.services.servicenow_scripted_fetch import fetch_matching_records, fetch_records

from ..context import ToolContext
from ..evidence_fields import with_source
from .common import _limit, _string

MAX_SCANNED_PER_CALL = 2000


def _coded(code: str, message: str | None = None) -> dict[str, Any]:
    return {"error": message or f"{code}: {MESSAGES[code]}", "code": code}


def table_api_disabled() -> dict[str, Any]:
    """The answer of a generic table tool on a Scripted REST connection."""
    return _coded(CODE_TABLE_API_DISABLED)


async def list_scripted(
    context: ToolContext, table: str, list_key: str, params: dict, *, base: str, headers: dict[str, str],
    auth: httpx.Auth | None,
) -> dict[str, Any]:
    """Page the configured endpoint of ``table`` up to the requested limit; normalised records with links."""
    if _string(params.get("query")):
        return _coded(CODE_QUERY_UNSUPPORTED)
    try:
        api = scripted_api(context.project_config)
    except ScriptedEndpointError as error:
        return _coded(error.code, str(error))
    path = api.paths.get(table) if api else None
    if not path:
        return _coded(CODE_ENDPOINT_NOT_CONFIGURED)
    limit = _limit(context, params, default=20, maximum=100)
    scope = record_limit(context.project_config)
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, transport=egress_transport(CONNECTION_SERVICENOW), auth=auth
        ) as client:
            if scope is None:
                records, total = await fetch_records(
                    client, base, path, table, limit=limit, page_size=api.page_size, headers=headers
                )
            else:
                records, _complete = await fetch_matching_records(
                    client, base, path, table, limit=limit, page_size=api.page_size, headers=headers,
                    keep=lambda record: record_in_limit(record, scope), max_scanned=MAX_SCANNED_PER_CALL,
                )
                total = None
    except (ScriptedEndpointError, OidcTokenError) as error:
        return _coded(error.code, str(error))
    items = []
    for record in records:
        normalized = normalize_record(record, table, base)
        title = " ".join(_string(normalized.get(key)) for key in ("number", "short_description")).strip()
        items.append(with_source(normalized, title=title or f"{table} {normalized.get('sys_id')}",
                                 url=normalized.get("url")))
    return {"count": len(items), "total": total, "api_style": "scripted", list_key: items}


__all__ = ["list_scripted", "table_api_disabled"]
