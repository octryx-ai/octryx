"""SharePoint connector tools."""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_MICROSOFT_GRAPH

from ..context import ToolContext
from ..evidence_fields import known_web_url, with_source
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string, connection_http_json
from .microsoft_graph import _microsoft_graph_token

#: This module's HTTP helpers use the microsoft_graph egress rule.
_http_json = connection_http_json(CONNECTION_MICROSOFT_GRAPH)


def _with_web_source(item: dict[str, Any], context: ToolContext, *, title: Any) -> dict[str, Any]:
    url = known_web_url(item.get("web_url"), _string(context.project_config.get("sharepoint_url")))
    return with_source(item, title=title, url=url)


def _sharepoint_site_paths(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("sharepoint_site_paths"))


async def _resolve_sharepoint_site(context: ToolContext, site_path: str) -> dict[str, Any]:
    sharepoint_url = _string(context.project_config.get("sharepoint_url"))
    host = sharepoint_url.replace("https://", "").replace("http://", "").strip("/")
    token = await _microsoft_graph_token(context, scope="https://graph.microsoft.com/.default")
    return await _http_json(
        "GET",
        f"https://graph.microsoft.com/v1.0/sites/{host}:{site_path}",
        headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
    )


class SearchSharePointTool:
    name = "search_sharepoint"
    description = "Search SharePoint sites via Microsoft Graph."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = _string(params.get("query"))
        if not query:
            return {"error": "query is required"}
        token = await _microsoft_graph_token(context, scope="https://graph.microsoft.com/.default")
        data = await _http_json(
            "GET",
            "https://graph.microsoft.com/v1.0/sites",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={"search": query},
        )
        sites = data.get("value") or []
        return {
            "query": query,
            "count": len(sites),
            "sites": [
                _with_web_source(
                    {"id": item.get("id"), "name": item.get("displayName"), "web_url": item.get("webUrl")},
                    context,
                    title=item.get("displayName"),
                )
                for item in sites[: _limit(context, params, default=10, maximum=50)]
            ],
        }


class ListSharePointSitePagesTool:
    name = "list_sharepoint_site_pages"
    description = "List pages of an allowed SharePoint site."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        site_path = _string(params.get("site_path"))
        allowed_paths = _sharepoint_site_paths(context)
        if not site_path and allowed_paths:
            site_path = allowed_paths[0]
        if not site_path:
            return {"error": "site_path is required"}
        if allowed_paths and site_path not in allowed_paths:
            return {"error": "site_path is not allowed"}
        site = await _resolve_sharepoint_site(context, site_path)
        token = await _microsoft_graph_token(context, scope="https://graph.microsoft.com/.default")
        data = await _http_json(
            "GET",
            f"https://graph.microsoft.com/v1.0/sites/{site.get('id')}/pages/microsoft.graph.sitePage",
            headers=_headers_with_bearer(token, extra={"Accept": "application/json"}),
            params={"$top": _limit(context, params, default=20, maximum=100)},
        )
        pages = data.get("value") or []
        return {
            "site_path": site_path,
            "site_id": site.get("id"),
            "count": len(pages),
            "pages": [
                _with_web_source(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "title": item.get("title"),
                        "web_url": item.get("webUrl"),
                        "last_modified": item.get("lastModifiedDateTime"),
                    },
                    context,
                    title=item.get("title") or item.get("name"),
                )
                for item in pages
            ],
        }
