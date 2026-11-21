"""Jira metadata lookup tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_helpers_api import _jira_fetch_project_metadata
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_default_project_key,
    _jira_http,
)


class ListJiraIssueTypes:
    name = "list_jira_issue_types"
    description = "List the issue types configured for a Jira project so the agent knows which ones are valid."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        project_key = str(params.get("project_key") or _jira_default_project_key(context) or "").strip().upper()
        allowed = _jira_allowed_projects(context)
        if allowed and project_key and project_key not in allowed:
            project_key = allowed[0] if len(allowed) == 1 else ""
        if not project_key:
            return {"error": "project_key is required"}

        if allowed and project_key not in allowed:
            return {"error": f"Project '{project_key}' is not in the allowed list: {allowed}"}

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            metadata, api_version = await _jira_fetch_project_metadata(
                client,
                jira_url,
                headers=headers,
                project_key=project_key,
            )

        issue_types = metadata.get("issueTypes") if isinstance(metadata, dict) else []
        return {
            "project_key": project_key,
            "api_version": api_version,
            "issue_types": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "subtask": bool(item.get("subtask")),
                }
                for item in (issue_types or [])
                if isinstance(item, dict)
            ],
        }


class ListJiraPriorities:
    name = "list_jira_priorities"
    description = "List the Jira priorities available for ticket creation and updates."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            payload, api_version = await _jira_helpers_api._jira_api_get(client, jira_url, "/priority", headers=headers)

        priorities = payload if isinstance(payload, list) else []
        return {
            "api_version": api_version,
            "priorities": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                }
                for item in priorities
                if isinstance(item, dict)
            ],
        }
