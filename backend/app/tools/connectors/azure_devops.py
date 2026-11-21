"""Azure DevOps connector tools."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from app.services.outbound_egress import CONNECTION_AZURE_DEVOPS

from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _limit, _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the azure_devops egress rule.
_http_json = connection_http_json(CONNECTION_AZURE_DEVOPS)


def _azure_devops_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("azure_devops_url")).rstrip("/")


def _azure_devops_headers(context: ToolContext) -> dict[str, str]:
    pat = _string(context.project_config.get("azure_devops_pat"))
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if pat:
        auth = base64.b64encode(f":{pat}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {auth}"
    return headers


def _azure_devops_allowed_projects(context: ToolContext) -> list[str]:
    return _normalize_string_list(
        context.project_config.get("azure_devops_allowed_projects")
        or context.project_config.get("azure_devops_project")
    )


def _resolve_azure_devops_project(context: ToolContext, params: dict[str, Any]) -> str | None:
    project = _string(
        params.get("project") or params.get("project_id") or context.project_config.get("azure_devops_project")
    )
    allowed = _azure_devops_allowed_projects(context)
    if not project and len(allowed) == 1:
        project = allowed[0]
    if not project:
        return None
    if allowed and project not in allowed:
        return None
    return project


class ListAzureDevOpsWorkItemsTool:
    name = "list_work_items"
    description = "List Azure DevOps work items for an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_azure_devops_project(context, params)
        base = _azure_devops_base_url(context)
        if not base:
            return {"error": "No Azure DevOps URL configured for this project"}
        if not project:
            return {"error": "project is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        work_item_type = _string(params.get("work_item_type") or "Issue")
        state = _string(params.get("state"))
        where = [f"[System.TeamProject] = '{project}'", f"[System.WorkItemType] = '{work_item_type}'"]
        if state:
            where.append(f"[System.State] = '{state}'")
        wiql = (
            "SELECT TOP "
            + str(limit)
            + " [System.Id], [System.Title], [System.State] FROM WorkItems WHERE "
            + " AND ".join(where)
            + " ORDER BY [System.ChangedDate] DESC"
        )
        query_payload = await _http_json(
            "POST",
            f"{base}/{quote(project, safe='')}/_apis/wit/wiql",
            headers=_azure_devops_headers(context),
            params={"api-version": "7.1"},
            json_body={"query": wiql},
        )
        refs = query_payload.get("workItems") or []
        ids = [str(item.get("id")) for item in refs if item.get("id") is not None]
        if not ids:
            return {"provider": "azure_devops", "project": project, "count": 0, "work_items": []}
        detail_payload = await _http_json(
            "GET",
            f"{base}/{quote(project, safe='')}/_apis/wit/workitems",
            headers=_azure_devops_headers(context),
            params={"api-version": "7.1", "ids": ",".join(ids)},
        )
        items = detail_payload.get("value") or []
        return {
            "provider": "azure_devops",
            "project": project,
            "count": len(items),
            # Each work item names its edit page on the configured organization (evidence fields).
            "work_items": [
                with_source(
                    {
                        "id": item.get("id"),
                        "title": ((item.get("fields") or {}).get("System.Title")),
                        "state": ((item.get("fields") or {}).get("System.State")),
                        "work_item_type": ((item.get("fields") or {}).get("System.WorkItemType")),
                        "assigned_to": (((item.get("fields") or {}).get("System.AssignedTo") or {}).get("displayName")),
                    },
                    title=f"{project} #{item.get('id')}: {(item.get('fields') or {}).get('System.Title') or ''}",
                    url=item_url(base, project, "_workitems", "edit", item.get("id")),
                )
                for item in items
            ],
        }


class ListAzureDevOpsPipelinesTool:
    name = "list_pipelines"
    description = "List Azure DevOps pipelines for an allowed project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_azure_devops_project(context, params)
        base = _azure_devops_base_url(context)
        if not base:
            return {"error": "No Azure DevOps URL configured for this project"}
        if not project:
            return {"error": "project is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        payload = await _http_json(
            "GET",
            f"{base}/{quote(project, safe='')}/_apis/pipelines",
            headers=_azure_devops_headers(context),
            params={"api-version": "7.1", "$top": limit},
        )
        items = payload.get("value") or []
        return {
            "provider": "azure_devops",
            "project": project,
            "count": len(items),
            # Each pipeline names its build page on the configured organization (evidence fields).
            "pipelines": [
                with_source(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "folder": item.get("folder"),
                        "revision": item.get("revision"),
                    },
                    title=f"{project} pipeline {item.get('name') or item.get('id')}",
                    url=item_url(base, project, "_build", query=f"definitionId={item.get('id')}")
                    if str(item.get("id") or "").isdigit()
                    else None,
                )
                for item in items[:limit]
            ],
        }
