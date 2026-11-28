"""Jira lookups that turn the asked assignee, priority, issue type and versions into what the project has."""

from __future__ import annotations

from typing import Any

import httpx

from . import _jira_helpers_api
from ._jira_helpers_resolver import (
    _jira_resolve_assignee_name,
    _jira_resolve_cloud_assignee,
    _jira_resolve_fix_version_refs,
    _jira_resolve_issue_type_name,
    _jira_resolve_priority_name,
)
from ._jira_ticket_fields import NewTicket

# Jira Cloud has no user names: an assignee that resolves to no single account is refused, never sent as a name.
UNRESOLVED_CLOUD_ASSIGNEE = (
    "The assignee could not be resolved to exactly one Jira Cloud account. "
    "Name the person by their display name, email or account id."
)


async def resolve_create_fields(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    ticket: NewTicket,
    fields: dict[str, Any],
    cloud: bool,
) -> tuple[dict[str, Any] | None, str]:
    project_key = ticket.project_key
    resolved_issue_type = await _jira_resolve_issue_type_name(
        client,
        jira_url,
        headers=headers,
        project_key=project_key,
        desired_name=ticket.issue_type,
    )
    fields["issuetype"] = {"name": resolved_issue_type}
    if ticket.assignee and cloud:
        account_id = await _jira_resolve_cloud_assignee(
            client, jira_url, headers=headers, project_key=project_key, desired_assignee=ticket.assignee
        )
        if account_id is None:
            return {"error": UNRESOLVED_CLOUD_ASSIGNEE}, resolved_issue_type
        fields["assignee"] = {"accountId": account_id}
    elif ticket.assignee:
        resolved_assignee = await _jira_resolve_assignee_name(
            client,
            jira_url,
            headers=headers,
            project_key=project_key,
            desired_assignee=ticket.assignee,
        )
        fields["assignee"] = {"name": resolved_assignee}
    await _resolve_priority_and_versions(
        client,
        jira_url,
        headers=headers,
        fields=fields,
        project_key=project_key,
        priority=ticket.priority,
        fix_versions=list(ticket.fix_versions) if ticket.fix_versions else None,
    )
    return None, resolved_issue_type


async def _resolve_priority_and_versions(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    fields: dict[str, Any],
    project_key: str,
    priority: str,
    fix_versions: list[Any] | None,
) -> None:
    if priority:
        resolved_priority = await _jira_resolve_priority_name(
            client,
            jira_url,
            headers=headers,
            desired_name=priority,
        )
        fields["priority"] = {"name": resolved_priority}
    if fix_versions is not None:
        fields["fixVersions"] = await _jira_resolve_fix_version_refs(
            client,
            jira_url,
            headers=headers,
            project_key=project_key,
            fix_versions=fix_versions,
        )


async def add_to_sprint(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], sprint_id: Any, result: dict[str, Any]
) -> None:
    # Optionally assign to sprint via Agile API
    if sprint_id and result.get("key"):
        try:
            await _jira_helpers_api._jira_agile_post(
                client,
                jira_url,
                f"/sprint/{sprint_id}/issue",
                headers=headers,
                payload={"issues": [result["key"]]},
            )
        except Exception:
            pass  # sprint assignment is best-effort


async def resolve_update_fields(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    fields: dict[str, Any],
    params: dict,
    ticket_id: str,
    cloud: bool,
) -> dict[str, Any] | None:
    ticket_project_key = str(ticket_id).split("-", 1)[0].upper()
    if params.get("assignee") is not None:
        error = await _resolve_update_assignee(
            client,
            jira_url,
            headers=headers,
            fields=fields,
            project_key=ticket_project_key,
            assignee_value=str(params.get("assignee") or "").strip(),
            cloud=cloud,
        )
        if error:
            return error
    await _resolve_priority_and_versions(
        client,
        jira_url,
        headers=headers,
        fields=fields,
        project_key=ticket_project_key,
        priority=str(params["priority"]) if params.get("priority") else "",
        fix_versions=list(params.get("fix_versions") or []) if params.get("fix_versions") is not None else None,
    )
    return None


async def _resolve_update_assignee(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    fields: dict[str, Any],
    project_key: str,
    assignee_value: str,
    cloud: bool,
) -> dict[str, Any] | None:
    if assignee_value and cloud:
        account_id = await _jira_resolve_cloud_assignee(
            client,
            jira_url,
            headers=headers,
            project_key=project_key,
            desired_assignee=assignee_value,
        )
        if account_id is None:
            return {"error": UNRESOLVED_CLOUD_ASSIGNEE}
        fields["assignee"] = {"accountId": account_id}
    elif assignee_value:
        resolved_assignee = await _jira_resolve_assignee_name(
            client,
            jira_url,
            headers=headers,
            project_key=project_key,
            desired_assignee=assignee_value,
        )
        fields["assignee"] = {"name": resolved_assignee}
    else:
        fields["assignee"] = None
    return None


__all__ = ["UNRESOLVED_CLOUD_ASSIGNEE", "add_to_sprint", "resolve_create_fields", "resolve_update_fields"]
