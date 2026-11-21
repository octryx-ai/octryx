"""Datadog connector tools."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.outbound_egress import CONNECTION_DATADOG

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the datadog egress rule.
_http_json = connection_http_json(CONNECTION_DATADOG)


def _datadog_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("datadog_url") or "https://api.datadoghq.com").rstrip("/")


def _datadog_headers(context: ToolContext) -> dict[str, str]:
    api_key = _string(context.project_config.get("datadog_api_key"))
    app_key = _string(context.project_config.get("datadog_app_key"))
    headers = {"Accept": "application/json"}
    if api_key:
        headers["DD-API-KEY"] = api_key
    if app_key:
        headers["DD-APPLICATION-KEY"] = app_key
    return headers


class QueryDatadogMetricsTool:
    name = "query_metrics"
    description = "Query Datadog metrics for a time range."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = _string(params.get("query"))
        if not query:
            return {"error": "query is required"}
        end = int(params.get("to") or time.time())
        start = int(params.get("from") or (end - 3600))
        data = await _http_json(
            "GET",
            f"{_datadog_base_url(context)}/api/v1/query",
            headers=_datadog_headers(context),
            params={"from": start, "to": end, "query": query},
        )
        series = data.get("series") or []
        return {
            "query": query,
            "from": start,
            "to": end,
            "count": len(series),
            "series": [
                {
                    "metric": item.get("metric"),
                    "scope": item.get("scope"),
                    "point_count": len(item.get("pointlist") or []),
                }
                for item in series
            ],
        }


class ListDatadogMonitorsTool:
    name = "list_monitors"
    description = "List Datadog monitors."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json(
            "GET",
            f"{_datadog_base_url(context)}/api/v1/monitor",
            headers=_datadog_headers(context),
            params={
                "monitor_tags": ",".join(_normalize_string_list(params.get("tags"))) or None,
                "name": _string(params.get("query")) or None,
            },
        )
        monitors = data if isinstance(data, list) else []
        return {
            "count": len(monitors[:limit]),
            "monitors": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "status": item.get("overall_state") or item.get("status"),
                }
                for item in monitors[:limit]
            ],
        }


class GetDatadogEventsTool:
    name = "get_events"
    description = "Get Datadog events for a time range."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        end = int(params.get("end") or time.time())
        start = int(params.get("start") or (end - 3600))
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json(
            "GET",
            f"{_datadog_base_url(context)}/api/v1/events",
            headers=_datadog_headers(context),
            params={
                "start": start,
                "end": end,
                "priority": _string(params.get("priority")) or None,
                "tags": ",".join(_normalize_string_list(params.get("tags"))) or None,
            },
        )
        events = data.get("events") or []
        return {
            "start": start,
            "end": end,
            "count": len(events[:limit]),
            "events": [
                {
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("text"),
                    "priority": item.get("priority"),
                    "date_happened": item.get("date_happened"),
                }
                for item in events[:limit]
            ],
        }


class GetDatadogApmTracesTool:
    name = "get_apm_traces"
    description = "Search Datadog APM traces."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        limit = _limit(context, params, default=20, maximum=100)
        payload = {
            "filter": {
                "query": _string(params.get("query") or params.get("service") or "*"),
                "from": _string(params.get("from") or (datetime.now(UTC) - timedelta(hours=1)).isoformat()),
                "to": _string(params.get("to") or datetime.now(UTC).isoformat()),
            },
            "page": {"limit": limit},
        }
        data = await _http_json(
            "POST",
            f"{_datadog_base_url(context)}/api/v2/apm/events/search",
            headers={**_datadog_headers(context), "Content-Type": "application/json"},
            json_body=payload,
        )
        traces = data.get("data") or []
        return {
            "count": len(traces),
            "traces": [
                {
                    "trace_id": ((item.get("attributes") or {}).get("attributes") or {}).get("trace_id"),
                    "service": ((item.get("attributes") or {}).get("attributes") or {}).get("service"),
                    "resource_name": ((item.get("attributes") or {}).get("attributes") or {}).get("resource_name"),
                    "duration_ns": ((item.get("attributes") or {}).get("attributes") or {}).get("duration"),
                }
                for item in traces
            ],
        }


class GetDatadogServiceMapTool:
    name = "get_service_map"
    description = "Get Datadog service dependency information."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        data = await _http_json(
            "GET",
            f"{_datadog_base_url(context)}/api/v1/service_dependencies",
            headers=_datadog_headers(context),
            params={"env": _string(params.get("env")) or None},
        )
        services = data.get("services") or []
        dependencies = data.get("dependencies") or []
        return {
            "service_count": len(services),
            "dependency_count": len(dependencies),
            "services": services,
            "dependencies": dependencies,
        }
