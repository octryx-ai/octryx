"""Notion connector tools."""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_NOTION

from ..context import ToolContext
from ..evidence_fields import vendor_web_url, with_source
from .common import _headers_with_bearer, _limit, _string, connection_http_json

#: This module's HTTP helpers use the notion egress rule.
_http_json = connection_http_json(CONNECTION_NOTION)


def _notion_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("notion_token"))
    return _headers_with_bearer(
        token or None,
        extra={"Notion-Version": "2022-06-28", "Content-Type": "application/json"},
    )


def _notion_base_url() -> str:
    return "https://api.notion.com/v1"


# The fixed public API above answers with page URLs on Notion's own web hosts; nothing else is a source.
NOTION_WEB_HOSTS = frozenset({"www.notion.so", "notion.so"})


def _with_page_source(item: dict[str, Any]) -> dict[str, Any]:
    return with_source(item, title=item.get("title") or item.get("id"), url=vendor_web_url(item.get("url"), NOTION_WEB_HOSTS))


def _notion_title(item: dict[str, Any]) -> str:
    title = ((item.get("properties") or {}).get("title") or {}).get("title") or []
    if title:
        return "".join(str(part.get("plain_text") or "") for part in title).strip()
    if item.get("object") == "page":
        for prop in (item.get("properties") or {}).values():
            if prop.get("type") == "title":
                return "".join(str(part.get("plain_text") or "") for part in prop.get("title") or []).strip()
    return _string((item.get("title") or [{}])[0].get("plain_text") if isinstance(item.get("title"), list) else "")


class SearchNotionPagesTool:
    name = "search_notion_pages"
    description = "Search pages and databases in Notion."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = _string(params.get("query"))
        if not query:
            return {"error": "query is required"}
        limit = _limit(context, params, default=10, maximum=100)
        filter_value = _string(params.get("filter") or "page")
        payload: dict[str, Any] = {"query": query, "page_size": limit}
        if filter_value in {"page", "database"}:
            payload["filter"] = {"property": "object", "value": filter_value}
        data = await _http_json(
            "POST",
            f"{_notion_base_url()}/search",
            headers=_notion_headers(context),
            json_body=payload,
        )
        results = data.get("results") or []
        return {
            "query": query,
            "count": len(results),
            # Each page names its Notion web URL (evidence fields).
            "results": [
                _with_page_source(
                    {
                        "id": item.get("id"),
                        "object": item.get("object"),
                        "title": _notion_title(item),
                        "url": item.get("url"),
                        "last_edited_time": item.get("last_edited_time"),
                    }
                )
                for item in results[:limit]
            ],
        }


class GetNotionPageTool:
    name = "get_notion_page"
    description = "Fetch Notion page metadata and first child blocks."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        page_id = _string(params.get("page_id"))
        if not page_id:
            return {"error": "page_id is required"}
        page = await _http_json(
            "GET",
            f"{_notion_base_url()}/pages/{page_id}",
            headers=_notion_headers(context),
        )
        children = await _http_json(
            "GET",
            f"{_notion_base_url()}/blocks/{page_id}/children",
            headers=_notion_headers(context),
            params={"page_size": _limit(context, params, default=20, maximum=100)},
        )
        return _with_page_source({
            "id": page.get("id"),
            "title": _notion_title(page),
            "url": page.get("url"),
            "last_edited_time": page.get("last_edited_time"),
            "properties": list((page.get("properties") or {}).keys()),
            "blocks": [
                {
                    "id": block.get("id"),
                    "type": block.get("type"),
                    "has_children": block.get("has_children"),
                }
                for block in (children.get("results") or [])
            ],
        })
