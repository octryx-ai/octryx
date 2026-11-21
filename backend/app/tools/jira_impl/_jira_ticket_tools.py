"""Jira create/update tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_cloud import is_jira_cloud
from ._jira_evidence import issue_url
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_check_project_allowed,
    _jira_http,
)
from ._jira_helpers_resolver import DEFAULT_JIRA_ISSUE_TYPE, _jira_resolve_issue_type_name
from ._jira_helpers_ticket import _maybe_block_change_with_approval
from ._jira_issue_type_args import normalize_issue_type_args
from ._jira_ticket_fields import create_fields, new_ticket, update_fields
from ._jira_ticket_resolution import add_to_sprint, resolve_create_fields, resolve_update_fields


async def _effective_issue_type(context: ToolContext, project_key: str, requested: str) -> str:
    """The issue type Jira will get, read from the project like ``execute`` resolves it.

    Gemma left out issue_type; the preview said "Improvement" (its own default) while the schema says
    "default: Task" and execute asked for Task. The person confirms the type Jira really gets. Unreadable project
    metadata shows the requested type."""
    jira_url = _jira_base_url(context)
    if not jira_url or not project_key:
        return requested
    headers = {"Accept": "application/json", **_jira_auth_headers(context)}
    try:
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            return await _jira_resolve_issue_type_name(
                client, jira_url, headers=headers, project_key=project_key, desired_name=requested
            )
    except Exception:  # noqa: BLE001 - the preview stays usable; execute resolves (and reports) the type itself
        return requested


class CreateJiraTicket:
    name = "create_jira_ticket"
    description = "Create a new Jira issue (ticket) in a project."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        params, conflict = normalize_issue_type_args(params)
        project_key = str(params.get("project_key") or "").strip().upper()
        summary = str(params.get("summary") or "").strip()
        if conflict:
            return {"kind": "jira_create", "title": "Create Jira ticket", "summary": conflict, "after": None,
                    "details": [conflict]}
        requested = str(params.get("issue_type") or DEFAULT_JIRA_ISSUE_TYPE).strip()
        issue_type = await _effective_issue_type(context, project_key, requested)
        details = ["A new Jira issue will be created with the following fields.", f"issue type: {issue_type}"]
        if issue_type.lower() != requested.lower():
            details.append(f"{project_key} has no issue type '{requested}'; Jira gets '{issue_type}'.")
        return {
            "kind": "jira_create",
            "title": "Create Jira ticket",
            "summary": f"{project_key or 'project'} / {issue_type}: {summary or 'new ticket'}",
            "after": {
                "project_key": project_key,
                "issue_type": issue_type,
                "summary": summary,
                "description": str(params.get("description") or "").strip(),
                "priority": str(params.get("priority") or "").strip(),
                "labels": list(params.get("labels") or []),
                "parent_key": str(params.get("parent_key") or "").strip().upper(),
            },
            "details": details,
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        params, conflict = normalize_issue_type_args(params)
        if conflict:
            return {"error": conflict, "code": "jira_issue_type_conflict"}
        project_key = str(params.get("project_key") or "").strip().upper()
        summary = str(params.get("summary") or "").strip()
        if not project_key or not summary:
            return {"error": "project_key and summary are required"}

        allowed = _jira_allowed_projects(context)
        if allowed and project_key not in allowed:
            return {"error": f"Project '{project_key}' is not in the allowed list: {allowed}"}
        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Create Jira ticket in {project_key}",
        )
        if blocked is not None:
            return blocked

        ticket = new_ticket(params, project_key=project_key, summary=summary)
        cloud = is_jira_cloud(jira_url, context.project_config)
        fields = create_fields(ticket, cloud=cloud)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            error, resolved_issue_type = await resolve_create_fields(
                client, jira_url, headers=headers, ticket=ticket, fields=fields, cloud=cloud
            )
            if error:
                return error
            body, api_version, status_code = await _jira_helpers_api._jira_api_post(
                client, jira_url, "/issue", headers=headers, payload={"fields": fields}
            )
            result = body or {}
            await add_to_sprint(client, jira_url, headers=headers, sprint_id=ticket.sprint_id, result=result)

        # The new issue's real page (without it a model wrote an invented
        # ``demo-shop.atlassian.net`` link for the ticket it had just created).
        # What Jira really got (otherwise the answer could say "Story" for a Task); the answer reports this.
        created = {
            "ticket_id": result.get("key"),
            "id": result.get("id"),
            "project_key": project_key,
            "issue_type": resolved_issue_type,
            "summary": summary,
            "api_version": api_version,
            "status_code": status_code,
            "status": "created",
            "url": issue_url(jira_url, result.get("key")),
        }
        return created if created["url"] else {key: value for key, value in created.items() if key != "url"}


class UpdateJiraTicket:
    name = "update_jira_ticket"
    description = (
        "Update fields of an existing Jira ticket: summary, description, assignee, "
        "priority, fix_versions (releases), labels, story_points."
    )

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        ticket_id = str(params.get("ticket_id") or "").strip()
        fields: dict[str, Any] = {}
        for key in ("summary", "description", "assignee", "priority", "fix_versions", "labels", "story_points"):
            if params.get(key) is not None:
                fields[key] = params.get(key)
        return {
            "kind": "jira_update",
            "title": "Update Jira ticket",
            "summary": f"{ticket_id or 'ticket'} field update",
            "before": {"ticket_id": ticket_id},
            "after": fields,
            "details": ["Only the fields below will be changed on the Jira ticket."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        ticket_id = str(params.get("ticket_id") or "").strip()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        err = _jira_check_project_allowed(ticket_id, _jira_allowed_projects(context))
        if err:
            return {"error": err}
        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Update Jira ticket {ticket_id}",
        )
        if blocked is not None:
            return blocked

        cloud = is_jira_cloud(jira_url, context.project_config)
        fields = update_fields(params, cloud=cloud)
        if not fields:
            return {"error": "No fields to update provided"}

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            error = await resolve_update_fields(
                client, jira_url, headers=headers, fields=fields, params=params, ticket_id=ticket_id, cloud=cloud
            )
            if error:
                return error
            status_code = await _jira_helpers_api._jira_api_put(
                client, jira_url, f"/issue/{ticket_id}", headers=headers, payload={"fields": fields}
            )

        return {
            "ticket_id": ticket_id,
            "updated_fields": list(fields.keys()),
            "status_code": status_code,
            "status": "updated",
        }
