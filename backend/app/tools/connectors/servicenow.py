"""ServiceNow connector tools.

The connector's record limit (``servicenow_assignment_groups``/``servicenow_services``,
``services/servicenow_record_limit.py``) limits every read: a Table API listing ANDs the limit's condition to the
query server-side and reads display values *and* values (``sysparm_display_value=all``) so each record is
re-checked client-side before it is returned in the representation the caller asked for; a single record outside
the limit answers like a missing one. While a limit is set, a query must be plain narrowing conditions (no leading
``OR``, no ``^NQ``, ``EQ`` or ``RLQUERY``; trailing ``ORDERBY`` is fine): anything else is refused, because an
ANDed condition cannot narrow it.
"""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_SERVICENOW
from app.services.servicenow_auth import CODE_API_INVALID, ServiceNowAuth, resolve_servicenow_auth
from app.services.servicenow_record_limit import FIELDS, collapse, record_in_limit, record_limit
from app.services.servicenow_record_query import widens, with_clause
from app.services.servicenow_scripted import CODE_TABLE_API_DISABLED, STYLE_SCRIPTED, STYLE_TABLE, api_style

from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _http_json, _limit, _normalize_string_list, _string
from .servicenow_scripted_tools import list_scripted, table_api_disabled


def _servicenow_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("servicenow_url")).rstrip("/")


def _servicenow_allowed_tables(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("servicenow_allowed_tables"))


def _servicenow_table_allowed(context: ToolContext, table: str) -> bool:
    allowed = _servicenow_allowed_tables(context)
    return bool(table) and (not allowed or table in allowed)


def _servicenow_auth(context: ToolContext) -> ServiceNowAuth | None:
    """The explicit mode's credential (``services/servicenow_auth.py``)."""
    return resolve_servicenow_auth(context.project_config)


async def _servicenow_headers(context: ToolContext) -> dict[str, str]:
    auth = _servicenow_auth(context)
    return {"Accept": "application/json", **(auth.headers() if auth else {})}


def _servicenow_token_auth(context: ToolContext) -> dict[str, Any]:
    """For client credentials, the token auth (cached, retried once on a 401); else nothing."""
    auth = _servicenow_auth(context)
    http_auth = auth.http_auth() if auth else None
    return {"auth": http_auth} if http_auth else {}


def _style_answer(context: ToolContext) -> dict[str, Any] | None:
    """For a generic table tool: ``None`` on the Table API, else the coded refusal (scripted or unknown style)."""
    style = api_style(context.project_config)
    if style == STYLE_TABLE:
        return None
    if style == STYLE_SCRIPTED:
        return table_api_disabled()
    return {"error": f"{CODE_API_INVALID}: servicenow_api_style must be table or scripted", "code": CODE_API_INVALID}


async def _scripted_list(context: ToolContext, table: str, list_key: str, params: dict) -> dict[str, Any] | None:
    """The incident/change listing on a Scripted REST connection; ``None`` on the Table API."""
    refused = _style_answer(context)
    if refused is None:
        return None
    if refused.get("code") != CODE_TABLE_API_DISABLED:
        return refused
    auth = _servicenow_auth(context)
    return await list_scripted(
        context, table, list_key, params, base=_servicenow_base_url(context),
        headers=await _servicenow_headers(context), auth=auth.http_auth() if auth else None,
    )


def with_record_source(record: dict[str, Any], base: str, table: str) -> dict[str, Any]:
    """A record names its form page on the configured instance: ``{base}/{table}.do?sys_id={sys_id}``.

    The form the ServiceNow Source Sync links (``services/knowledge/sources/sync/servicenow.py``); no
    configured base, table or alphanumeric ``sys_id``: no source fields.
    """
    sys_id = _string(record.get("sys_id"))
    url = item_url(base, f"{table}.do", query=f"sys_id={sys_id}") if table and sys_id.isalnum() else None
    title = " ".join(part for part in (_string(record.get("number")), _string(record.get("short_description"))) if part)
    return with_source(record, title=title or f"{table} {sys_id}", url=url)


GROUP_QUERY_REFUSED = (
    "servicenow_query_widens_group_limit: this connector is limited to its assignment groups/services; the query "
    "must be plain conditions (no leading OR, no ^NQ, EQ or RLQUERY), optionally followed by ORDERBY."
)


def _fields(value: Any) -> str | None:
    if isinstance(value, list):
        return ",".join(_string(item) for item in value if _string(item)) or None
    return _string(value) or None if value is not None else None


def _with_limit_fields(fields: str | None, scope: Any) -> str | None:
    """The requested fields plus the limited fields (the client-side check reads them) under a record limit."""
    if scope is None or not fields:
        return fields
    names = [name.strip() for name in fields.split(",") if name.strip()]
    return ",".join([*names, *(spec.reference for spec in FIELDS if spec.reference not in names)])


def _in_limit(records: list[Any], scope: Any, display: str) -> list[Any]:
    """Without a limit, ``records`` as answered; with one, only records inside it, in the asked representation."""
    if scope is None:
        return records
    return [collapse(record, display) for record in records
            if isinstance(record, dict) and record_in_limit(record, scope)]


def _servicenow_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sys_id": record.get("sys_id"),
        "number": record.get("number"),
        "short_description": record.get("short_description"),
        "state": record.get("state"),
        "priority": record.get("priority"),
        "assignment_group": record.get("assignment_group"),
        "assigned_to": record.get("assigned_to"),
        "updated_on": record.get("sys_updated_on"),
    }


class ListServiceNowRecordsTool:
    name = "list_servicenow_records"
    description = "List records from an allowed ServiceNow table using sysparm_query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if (refused := _style_answer(context)) is not None:
            return refused
        base = _servicenow_base_url(context)
        table = _string(params.get("table"))
        if not base:
            return {"error": "No ServiceNow URL configured for this project"}
        if not table:
            return {"error": "table is required"}
        if not _servicenow_table_allowed(context, table):
            return {"error": f"table '{table}' is not allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        fields = _fields(params.get("fields"))
        scope = record_limit(context.project_config)
        query = _string(params.get("query")) or None
        if scope is not None and widens(query):
            return {"error": GROUP_QUERY_REFUSED, "code": "servicenow_query_widens_group_limit"}
        display = _string(params.get("display_value") or "true")
        try:
            data = await _http_json(
                "GET",
                f"{base}/api/now/table/{table}",
                headers=await _servicenow_headers(context),
                connection=CONNECTION_SERVICENOW,
                **_servicenow_token_auth(context),
                params={
                    "sysparm_limit": limit,
                    "sysparm_query": with_clause(query, scope),
                    "sysparm_fields": _with_limit_fields(fields, scope),
                    "sysparm_display_value": "all" if scope is not None else display,
                    "sysparm_exclude_reference_link": "true",
                },
            )
        except Exception as exc:
            return {"error": str(exc)}
        results = _in_limit(data.get("result") or [], scope, display)
        # Each record names its form page on the configured instance (evidence fields).
        records = [with_record_source(item, base, table) if isinstance(item, dict) else item for item in results[:limit]]
        return {"table": table, "count": len(results), "records": records}


class GetServiceNowRecordTool:
    name = "get_servicenow_record"
    description = "Get a specific record by sys_id from an allowed ServiceNow table."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _servicenow_base_url(context)
        table = _string(params.get("table"))
        sys_id = _string(params.get("sys_id"))
        if (refused := _style_answer(context)) is not None:
            return refused
        if not base:
            return {"error": "No ServiceNow URL configured for this project"}
        if not table or not sys_id:
            return {"error": "table and sys_id are required"}
        if not _servicenow_table_allowed(context, table):
            return {"error": f"table '{table}' is not allowed"}
        fields = _fields(params.get("fields"))
        scope = record_limit(context.project_config)
        display = _string(params.get("display_value") or "true")
        try:
            data = await _http_json(
                "GET",
                f"{base}/api/now/table/{table}/{sys_id}",
                headers=await _servicenow_headers(context),
                connection=CONNECTION_SERVICENOW,
                **_servicenow_token_auth(context),
                params={
                    "sysparm_fields": _with_limit_fields(fields, scope),
                    "sysparm_display_value": "all" if scope is not None else display,
                    "sysparm_exclude_reference_link": "true",
                },
            )
        except Exception as exc:
            return {"error": str(exc)}
        record = data.get("result") or {}
        if scope is not None:
            kept = _in_limit([record], scope, display)
            if not kept:  # another group's record answers like a missing one
                return {"error": f"record '{sys_id}' not found in table '{table}'", "code": "servicenow_record_not_found"}
            record = kept[0]
        record = {"sys_id": sys_id, **record} if isinstance(record, dict) else record
        return {"table": table, "record": with_record_source(record, base, table) if isinstance(record, dict) else record}


class ListServiceNowIncidentsTool:
    name = "list_servicenow_incidents"
    description = "List incident records from ServiceNow."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _servicenow_table_allowed(context, "incident"):
            return {"error": "table 'incident' is not allowed"}
        if (scripted := await _scripted_list(context, "incident", "incidents", params)) is not None:
            return scripted
        result = await ListServiceNowRecordsTool().execute(
            {
                "table": "incident",
                "query": params.get("query"),
                "limit": params.get("limit"),
                "fields": params.get("fields")
                or [
                    "sys_id",
                    "number",
                    "short_description",
                    "state",
                    "priority",
                    "assignment_group",
                    "assigned_to",
                    "sys_updated_on",
                ],
            },
            context,
        )
        if result.get("error"):
            return result
        return {
            "count": result.get("count", 0),
            "incidents": [
                with_record_source(_servicenow_record_summary(record), _servicenow_base_url(context), "incident")
                for record in result.get("records") or []
            ],
        }


class ListServiceNowChangesTool:
    name = "list_servicenow_changes"
    description = "List change request records from ServiceNow."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _servicenow_table_allowed(context, "change_request"):
            return {"error": "table 'change_request' is not allowed"}
        if (scripted := await _scripted_list(context, "change_request", "changes", params)) is not None:
            return scripted
        result = await ListServiceNowRecordsTool().execute(
            {
                "table": "change_request",
                "query": params.get("query"),
                "limit": params.get("limit"),
                "fields": params.get("fields")
                or [
                    "sys_id",
                    "number",
                    "short_description",
                    "state",
                    "priority",
                    "assignment_group",
                    "assigned_to",
                    "sys_updated_on",
                ],
            },
            context,
        )
        if result.get("error"):
            return result
        return {
            "count": result.get("count", 0),
            "changes": [
                with_record_source(_servicenow_record_summary(record), _servicenow_base_url(context), "change_request")
                for record in result.get("records") or []
            ],
        }
