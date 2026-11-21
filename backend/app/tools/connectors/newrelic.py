"""New Relic connector tools."""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_NEWRELIC

from ..context import ToolContext
from .common import _limit, _string, connection_http_json
from .splunk import _splunk_export_search

#: This module's HTTP helpers use the newrelic egress rule.
_http_json = connection_http_json(CONNECTION_NEWRELIC)


def _newrelic_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("newrelic_url") or "https://api.newrelic.com").rstrip("/")


def _newrelic_headers(context: ToolContext) -> dict[str, str]:
    api_key = _string(context.project_config.get("newrelic_api_key"))
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Api-Key"] = api_key
    return headers


def _newrelic_account_id(context: ToolContext, params: dict[str, Any]) -> int:
    raw = _string(params.get("account_id") or context.project_config.get("newrelic_account_id"))
    if not raw:
        raise ValueError("account_id is required")
    return int(raw)


async def _newrelic_graphql(context: ToolContext, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = await _http_json(
        "POST",
        f"{_newrelic_base_url(context)}/graphql",
        headers={**_newrelic_headers(context), "Content-Type": "application/json"},
        json_body={"query": query, "variables": variables},
    )
    errors = payload.get("errors") or []
    if errors:
        raise ValueError(_string(errors[0].get("message")) or "New Relic query failed")
    return payload.get("data") or {}


class QueryNewRelicNrqlTool:
    name = "nrql_query"
    description = "Run a New Relic NRQL query."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = _string(params.get("query"))
        if not query:
            return {"error": "query is required"}
        account_id = _newrelic_account_id(context, params)
        data = await _newrelic_graphql(
            context,
            """
            query($accountId:Int!, $query:String!) {
              actor {
                account(id: $accountId) {
                  nrql(query: $query) {
                    results
                  }
                }
              }
            }
            """,
            {"accountId": account_id, "query": query},
        )
        results = (((data.get("actor") or {}).get("account") or {}).get("nrql") or {}).get("results") or []
        return {"account_id": account_id, "query": query, "count": len(results), "results": results}


class GetNewRelicAlertsTool:
    name = "get_alerts"
    description = "Get alerts from New Relic."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        provider = _string(params.get("provider")).lower()
        if provider == "splunk":
            rows = await _splunk_export_search(
                context,
                'search index="*" ":"',
            )
            return {
                "provider": "splunk",
                "count": len(rows),
                "alerts": [
                    {
                        "name": row.get("name") or row.get("title") or row.get("alert_name") or row.get("alert_id"),
                        "status": row.get("status"),
                        "index": row.get("index"),
                    }
                    for row in rows
                ],
            }
        data = await _http_json(
            "GET",
            f"{_newrelic_base_url(context)}/v2/alerts_violations.json",
            headers=_newrelic_headers(context),
            params={"only_open": "true"},
        )
        violations = data.get("violations") or []
        limit = _limit(context, params, default=20, maximum=100)
        return {
            "provider": "newrelic",
            "count": len(violations[:limit]),
            "alerts": [
                {
                    "id": item.get("id"),
                    # The incident the violation belongs to: its page is the citable source.
                    "incident_id": (item.get("links") or {}).get("incident_id"),
                    "label": item.get("label"),
                    "entity": item.get("entity") or {},
                    "priority": item.get("priority"),
                    "state": item.get("state"),
                }
                for item in violations[:limit]
            ],
        }


class GetNewRelicApmDataTool:
    name = "get_apm_data"
    description = "Get New Relic APM application data."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        account_id = _newrelic_account_id(context, params)
        entity_name = _string(params.get("entity_name") or params.get("service_name"))
        data = await _newrelic_graphql(
            context,
            """
            query($accountId:Int!, $name:String!) {
              actor {
                entitySearch(query: $name) {
                  results {
                    entities {
                      guid
                      name
                      type
                      domain
                      reporting
                      alertSeverity
                    }
                  }
                }
                account(id: $accountId) {
                  nrql(query: "SELECT average(duration) AS avgDuration, percentage(count(*), WHERE error IS true) AS errorRate FROM Transaction TIMESERIES") {
                    results
                  }
                }
              }
            }
            """,
            {"accountId": account_id, "name": entity_name or "type = 'APPLICATION'"},
        )
        entities = ((((data.get("actor") or {}).get("entitySearch") or {}).get("results")) or {}).get("entities") or []
        metrics = (((data.get("actor") or {}).get("account") or {}).get("nrql") or {}).get("results") or []
        return {
            "account_id": account_id,
            "entity_name": entity_name,
            "entity_count": len(entities),
            "entities": entities,
            "metrics": metrics,
        }
