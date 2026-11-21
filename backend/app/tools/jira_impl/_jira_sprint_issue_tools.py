"""Jira sprint issue list/assignment tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_allowlist import allowed_issues
from ._jira_evidence import with_issue_source
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_check_project_allowed,
    _jira_http,
)


class GetSprintIssues:
    name = "get_sprint_issues"
    description = "List all issues assigned to a Jira sprint."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        sprint_id = str(params.get("sprint_id") or "").strip()
        if not sprint_id:
            return {"error": "sprint_id is required"}

        limit = max(1, min(int(params.get("limit") or 50), 100))
        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            data = await _jira_helpers_api._jira_agile_get(
                client,
                jira_url,
                f"/sprint/{sprint_id}/issue",
                headers=headers,
                params={
                    "maxResults": limit,
                    "fields": "summary,status,assignee,priority,issuetype,story_points,customfield_10016,fixVersions",
                },
            )

        # Only issues of allowed projects (key project, matching fields.project).
        issues = allowed_issues(data.get("issues", []), _jira_allowed_projects(context))
        result = []
        for issue in issues:
            fields = issue.get("fields", {})
            result.append(
                {
                    "ticket_id": issue.get("key"),
                    "summary": fields.get("summary"),
                    "status": (fields.get("status") or {}).get("name"),
                    "assignee": (fields.get("assignee") or {}).get("displayName"),
                    "priority": (fields.get("priority") or {}).get("name"),
                    "issue_type": (fields.get("issuetype") or {}).get("name"),
                    "story_points": fields.get("customfield_10016"),
                    "fix_versions": [v.get("name") for v in (fields.get("fixVersions") or [])],
                }
            )

        # Each ticket names its /browse page on the configured Jira (evidence fields).
        result = [with_issue_source(item, jira_url) for item in result]
        return {"sprint_id": sprint_id, "total": len(result), "issues": result}


class AddIssuesToSprint:
    name = "add_issues_to_sprint"
    description = "Assign one or more Jira issues to a sprint."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        sprint_id = str(params.get("sprint_id") or "").strip()
        ticket_ids = params.get("ticket_ids") or []
        if not sprint_id:
            return {"error": "sprint_id is required"}
        if not ticket_ids:
            return {"error": "ticket_ids (list) is required"}

        allowed = _jira_allowed_projects(context)
        for tid in ticket_ids:
            err = _jira_check_project_allowed(str(tid), allowed)
            if err:
                return {"error": err}

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            _, status_code = await _jira_helpers_api._jira_agile_post(
                client,
                jira_url,
                f"/sprint/{sprint_id}/issue",
                headers=headers,
                payload={"issues": [str(t) for t in ticket_ids]},
            )

        return {
            "sprint_id": sprint_id,
            "ticket_ids": ticket_ids,
            "status_code": status_code,
            "status": "added_to_sprint",
        }
