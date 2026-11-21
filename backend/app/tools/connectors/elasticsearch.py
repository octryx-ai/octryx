"""Elasticsearch connector tools."""

from __future__ import annotations

import json
from typing import Any

from app.services.outbound_egress import CONNECTION_ELASTICSEARCH

from ..context import ToolContext
from .common import _headers_with_basic, _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the elasticsearch egress rule.
_http_json = connection_http_json(CONNECTION_ELASTICSEARCH)


def _elasticsearch_headers(context: ToolContext) -> dict[str, str]:
    api_key = _string(context.project_config.get("elasticsearch_api_key"))
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    username = _string(context.project_config.get("elasticsearch_username"))
    password = _string(context.project_config.get("elasticsearch_password"))
    return _headers_with_basic(username or None, password or None)


def _elasticsearch_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("elasticsearch_url")).rstrip("/")


def _elasticsearch_allowed_indices(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("elasticsearch_allowed_indices"))


class GetElasticsearchClusterHealthTool:
    name = "get_elasticsearch_cluster_health"
    description = "Read Elasticsearch cluster health."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _elasticsearch_base_url(context)
        if not base:
            return {"error": "No Elasticsearch URL configured for this project"}
        data = await _http_json("GET", f"{base}/_cluster/health", headers=_elasticsearch_headers(context))
        return {
            "cluster_name": data.get("cluster_name"),
            "status": data.get("status"),
            "number_of_nodes": data.get("number_of_nodes"),
            "active_primary_shards": data.get("active_primary_shards"),
            "active_shards": data.get("active_shards"),
            "unassigned_shards": data.get("unassigned_shards"),
        }


class SearchElasticsearchDocumentsTool:
    name = "search_elasticsearch_documents"
    description = "Run a search against an allowed Elasticsearch index."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _elasticsearch_base_url(context)
        if not base:
            return {"error": "No Elasticsearch URL configured for this project"}
        index = _string(params.get("index"))
        allowed = _elasticsearch_allowed_indices(context)
        if not index:
            if len(allowed) == 1:
                index = allowed[0]
            else:
                return {"error": "index is required"}
        if allowed and index not in allowed:
            return {"error": "index is not allowed"}
        limit = _limit(context, params, default=10, maximum=100)
        body = params.get("query_body")
        if isinstance(body, str) and body.strip():
            body = json.loads(body)
        if not isinstance(body, dict):
            query_string = _string(params.get("query"))
            if not query_string:
                return {"error": "query or query_body is required"}
            body = {"query": {"query_string": {"query": query_string}}, "size": limit}
        body.setdefault("size", limit)
        data = await _http_json(
            "POST",
            f"{base}/{index}/_search",
            headers=_elasticsearch_headers(context),
            json_body=body,
            timeout=60,
        )
        hits = (((data.get("hits") or {}).get("hits")) or [])[:limit]
        return {
            "index": index,
            "total": ((data.get("hits") or {}).get("total") or {}).get("value"),
            "hits": [
                {"_id": hit.get("_id"), "_score": hit.get("_score"), "_source": hit.get("_source")} for hit in hits
            ],
        }
