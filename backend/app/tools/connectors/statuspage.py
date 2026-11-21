"""Statuspage incident connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_STATUSPAGE

from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_form_json, connection_http_json

#: This module's HTTP helpers use the statuspage egress rule.
_http_form_json = connection_http_form_json(CONNECTION_STATUSPAGE)
_http_json = connection_http_json(CONNECTION_STATUSPAGE)


def _statuspage_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("statuspage_url") or "https://api.statuspage.io").rstrip("/")


def _statuspage_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("statuspage_api_key"))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"OAuth {token}"
    return headers


def _resolve_allowed_identifier(value: Any, *, allowed: list[str]) -> str | None:
    candidate = _string(value)
    if not candidate and len(allowed) == 1:
        candidate = allowed[0]
    if not candidate:
        return None
    if allowed and candidate not in allowed:
        return None
    return candidate


def _statuspage_page_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return _resolve_allowed_identifier(
        params.get("page_id") or context.project_config.get("statuspage_page_id"),
        allowed=_normalize_string_list(context.project_config.get("statuspage_allowed_page_ids")),
    )


def _statuspage_allowed_component_ids(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("statuspage_allowed_component_ids"))


def _statuspage_component_ids(context: ToolContext, params: dict[str, Any]) -> list[str]:
    allowed = _statuspage_allowed_component_ids(context)
    candidates = _normalize_string_list(params.get("component_ids"))
    if not candidates:
        return []
    if allowed:
        return [item for item in candidates if item in allowed]
    return candidates


def _normalize_statuspage_incident(incident: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": incident.get("id"),
        "name": incident.get("name"),
        "status": incident.get("status"),
        "impact": incident.get("impact"),
        "shortlink": incident.get("shortlink"),
        "created_at": incident.get("created_at"),
        "updated_at": incident.get("updated_at"),
        "incident_updates": incident.get("incident_updates") or [],
    }


def _normalize_statuspage_component(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": component.get("id"),
        "name": component.get("name"),
        "status": component.get("status"),
        "group": component.get("group"),
        "description": component.get("description"),
        "updated_at": component.get("updated_at"),
    }


class StatuspageCreateIncidentTool:
    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        title = _string(params.get("title") or params.get("message"))
        if not title:
            return {"error": "title is required"}
        page_id = _statuspage_page_id(context, params)
        if not page_id:
            return {"error": "page_id is required and must be allowed"}
        details = _string(params.get("details") or params.get("description"))
        incident_status = _string(params.get("status") or "investigating").lower() or "investigating"
        form_data: dict[str, Any] = {
            "incident[name]": title,
            "incident[status]": incident_status,
            "incident[body]": details or title,
        }
        for component_id in _statuspage_component_ids(context, params):
            form_data.setdefault("incident[component_ids][]", [])
            form_data["incident[component_ids][]"].append(component_id)
        impact_override = _string(params.get("impact_override"))
        if impact_override:
            form_data["incident[impact_override]"] = impact_override
        component_status = _string(params.get("component_status"))
        if component_status and form_data.get("incident[component_ids][]"):
            for component_id in form_data["incident[component_ids][]"]:
                form_data[f"incident[components][{component_id}]"] = component_status
        data = await _http_form_json(
            "POST",
            f"{_statuspage_base_url(context)}/v1/pages/{quote(page_id, safe='')}/incidents",
            headers=_statuspage_headers(context),
            form_data=form_data,
        )
        return {"provider": "statuspage", "incident": _normalize_statuspage_incident(data), "raw": data}


class UpdateIncidentTool:
    name = "update_incident"
    description = "Update a Statuspage incident."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        page_id = _statuspage_page_id(context, params)
        incident_id = _string(params.get("incident_id"))
        if not page_id:
            return {"error": "page_id is required and must be allowed"}
        if not incident_id:
            return {"error": "incident_id is required"}
        form_data: dict[str, Any] = {}
        title = _string(params.get("title") or params.get("name"))
        if title:
            form_data["incident[name]"] = title
        status = _string(params.get("status"))
        if status:
            form_data["incident[status]"] = status
        body = _string(params.get("body") or params.get("details") or params.get("message"))
        if body:
            form_data["incident[body]"] = body
        component_status = _string(params.get("component_status"))
        for component_id in _statuspage_component_ids(context, params):
            form_data.setdefault("incident[component_ids][]", [])
            form_data["incident[component_ids][]"].append(component_id)
            if component_status:
                form_data[f"incident[components][{component_id}]"] = component_status
        if not form_data:
            return {"error": "At least one field to update is required"}
        data = await _http_form_json(
            "PATCH",
            f"{_statuspage_base_url(context)}/v1/pages/{quote(page_id, safe='')}/incidents/{quote(incident_id, safe='')}",
            headers=_statuspage_headers(context),
            form_data=form_data,
        )
        return {"incident": _normalize_statuspage_incident(data), "raw": data}


class ResolveStatuspageIncidentTool:
    name = "resolve_incident"
    description = "Resolve a Statuspage incident."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        merged = dict(params)
        merged.setdefault("status", "resolved")
        result = await UpdateIncidentTool().execute(merged, context)
        if result.get("error"):
            return result
        return {"status": "resolved", "incident": result.get("incident"), "raw": result.get("raw")}


class ListStatuspageComponentsTool:
    name = "list_components"
    description = "List Atlassian Statuspage components for the configured page."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        page_id = _statuspage_page_id(context, params)
        if not page_id:
            return {"error": "page_id is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        data = await _http_json(
            "GET",
            f"{_statuspage_base_url(context)}/v1/pages/{quote(page_id, safe='')}/components",
            headers=_statuspage_headers(context),
        )
        components = data if isinstance(data, list) else []
        allowed = _statuspage_allowed_component_ids(context)
        if allowed:
            components = [item for item in components if _string(item.get("id")) in allowed]
        return {
            "count": len(components[:limit]),
            "components": [_normalize_statuspage_component(item) for item in components[:limit]],
        }


class UpdateStatuspageComponentStatusTool:
    name = "update_component_status"
    description = "Update the status of a Statuspage component."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        page_id = _statuspage_page_id(context, params)
        component_id = _string(params.get("component_id"))
        status = _string(params.get("status"))
        if not page_id:
            return {"error": "page_id is required and must be allowed"}
        if not component_id:
            return {"error": "component_id is required"}
        allowed = _statuspage_allowed_component_ids(context)
        if allowed and component_id not in allowed:
            return {"error": "component_id is not allowed"}
        if not status:
            return {"error": "status is required"}
        data = await _http_form_json(
            "PATCH",
            f"{_statuspage_base_url(context)}/v1/pages/{quote(page_id, safe='')}/components/{quote(component_id, safe='')}",
            headers=_statuspage_headers(context),
            form_data={"component[status]": status},
        )
        return {"component": _normalize_statuspage_component(data), "raw": data}
