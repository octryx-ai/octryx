"""Splunk connector tools."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_SPLUNK, egress_transport

from ..context import ToolContext
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string


def _splunk_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("splunk_url")).rstrip("/")


def _splunk_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("splunk_token"))
    if token:
        return _headers_with_bearer(token, extra={"Accept": "application/json"})
    return {"Accept": "application/json"}


def _splunk_auth(context: ToolContext) -> tuple[str, str] | None:
    username = _string(context.project_config.get("splunk_username"))
    password = _string(context.project_config.get("splunk_password"))
    if username and password:
        return (username, password)
    return None


async def _splunk_json(
    context: ToolContext,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    form_data: dict[str, Any] | None = None,
) -> Any:
    base = _splunk_base_url(context)
    if not base:
        raise ValueError("splunk_url is required")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_SPLUNK)) as client:
        response = await client.request(
            method,
            f"{base}{path}",
            headers=_splunk_headers(context),
            params=params,
            data=form_data,
            auth=_splunk_auth(context),
        )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


async def _splunk_export_search(
    context: ToolContext, search: str, *, earliest_time: str | None = None, latest_time: str | None = None
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"search": search, "output_mode": "json"}
    if earliest_time:
        payload["earliest_time"] = earliest_time
    if latest_time:
        payload["latest_time"] = latest_time
    base = _splunk_base_url(context)
    if not base:
        raise ValueError("splunk_url is required")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_SPLUNK)) as client:
        response = await client.post(
            f"{base}/services/search/jobs/export",
            headers=_splunk_headers(context),
            data=payload,
            auth=_splunk_auth(context),
        )
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("result"), dict):
            rows.append(parsed["result"])
        elif isinstance(parsed, dict):
            rows.append(parsed)
    return rows


class SearchSplunkLogsTool:
    name = "search_logs"
    description = "Run a Splunk SPL search and return structured results."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = _string(params.get("query") or params.get("search"))
        if not query:
            return {"error": "query is required"}
        allowed_indexes = _normalize_string_list(context.project_config.get("splunk_allowed_indexes"))
        if allowed_indexes:
            query_lower = query.lower()
            if not any(f"index={item.lower()}" in query_lower for item in allowed_indexes):
                return {"error": "query must reference an allowed Splunk index"}
        try:
            rows = await _splunk_export_search(
                context,
                query,
                earliest_time=_string(params.get("earliest_time")) or None,
                latest_time=_string(params.get("latest_time")) or None,
            )
        except Exception as exc:
            return {"error": str(exc)}
        limit = _limit(context, params, default=20, maximum=200)
        return {"query": query, "count": len(rows[:limit]), "results": rows[:limit]}


class GetSplunkSavedSearchesTool:
    name = "get_saved_searches"
    description = "List Splunk saved searches."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _splunk_json(
                context,
                "GET",
                "/servicesNS/-/-/saved/searches",
                params={"output_mode": "json", "count": _limit(context, params, default=20, maximum=100)},
            )
        except Exception as exc:
            return {"error": str(exc)}
        entries = data.get("entry") or []
        return {
            "count": len(entries),
            "searches": [
                {
                    "name": item.get("name"),
                    "disabled": ((item.get("content") or {}).get("disabled")),
                    "search": ((item.get("content") or {}).get("search")),
                    "cron_schedule": ((item.get("content") or {}).get("cron_schedule")),
                    "alert_condition": ((item.get("content") or {}).get("alert_condition")),
                }
                for item in entries
            ],
        }


class GetSplunkIndexStatsTool:
    name = "get_index_stats"
    description = "Return index-level event counts from Splunk."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        indexes = _normalize_string_list(context.project_config.get("splunk_allowed_indexes"))
        query = (
            "search " + " OR ".join(f"index={item}" for item in indexes) + " | stats count by index"
            if indexes
            else "| eventcount summarize=false index=* | table index count"
        )
        try:
            rows = await _splunk_export_search(context, query)
        except Exception as exc:
            return {"error": str(exc)}
        return {"count": len(rows), "indexes": rows}
