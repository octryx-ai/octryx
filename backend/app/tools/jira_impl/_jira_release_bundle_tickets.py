"""The ticket side of ``create_jira_release_bundle`` and the bundle run in its write order."""

from __future__ import annotations

from typing import Any

import httpx

from . import _jira_helpers_api
from ._jira_cloud import rich_text_body
from ._jira_helpers_context import _jira_check_project_allowed
from ._jira_helpers_resolver import (
    _jira_resolve_assignee_name,
    _jira_resolve_issue_type_name,
    _jira_resolve_priority_name,
)
from ._jira_helpers_ticket import _extract_ticket_references
from ._jira_release_bundle_version import (
    BundleRequest,
    ReleaseVersion,
    ensure_release_version,
    release_version,
    resolve_cloud_accounts,
)


async def _new_ticket_fields(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: BundleRequest,
    ticket: dict[str, Any],
    version: ReleaseVersion,
    cloud_accounts: dict[str, str],
) -> tuple[dict[str, Any], str, str]:
    summary = str(ticket.get("summary") or "").strip()
    description = str(ticket.get("description") or "").strip()
    issue_type = str(ticket.get("issue_type") or request.issue_type_default).strip() or request.issue_type_default
    assignee = str(ticket.get("assignee") or "").strip()
    priority = str(ticket.get("priority") or "").strip()
    labels = [str(item).strip() for item in (ticket.get("labels") or []) if str(item).strip()]
    resolved_assignee = ""
    resolved_priority = ""
    fields: dict[str, Any] = {
        "project": {"key": request.project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
        "fixVersions": version.fix_versions(),
    }
    if description:
        fields["description"] = rich_text_body(description, cloud=request.cloud)
    if assignee and request.cloud:
        resolved_assignee = assignee
        fields["assignee"] = {"accountId": cloud_accounts[assignee]}
    elif assignee:
        resolved_assignee = await _jira_resolve_assignee_name(
            client,
            jira_url,
            headers=headers,
            project_key=request.project_key,
            desired_assignee=assignee,
        )
        fields["assignee"] = {"name": resolved_assignee}
    if priority:
        resolved_priority = await _jira_resolve_priority_name(
            client,
            jira_url,
            headers=headers,
            desired_name=priority,
        )
        fields["priority"] = {"name": resolved_priority}
    if labels:
        fields["labels"] = labels
    if ticket.get("story_points") is not None:
        fields["customfield_10016"] = ticket.get("story_points")
    return fields, resolved_assignee, resolved_priority


async def _create_ticket(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: BundleRequest,
    ticket: dict[str, Any],
    version: ReleaseVersion,
    cloud_accounts: dict[str, str],
) -> dict[str, Any]:
    fields, resolved_assignee, resolved_priority = await _new_ticket_fields(
        client, jira_url, headers=headers, request=request, ticket=ticket, version=version,
        cloud_accounts=cloud_accounts,
    )
    resolved_issue_type = await _jira_resolve_issue_type_name(
        client,
        jira_url,
        headers=headers,
        project_key=request.project_key,
        desired_name=fields["issuetype"]["name"],
    )
    fields["issuetype"] = {"name": resolved_issue_type}

    body, _, _ = await _jira_helpers_api._jira_api_post(
        client,
        jira_url,
        "/issue",
        headers=headers,
        payload={"fields": fields},
    )
    issue_result = body or {}
    description = str(ticket.get("description") or "").strip()
    return {
        "ticket_id": issue_result.get("key"),
        "id": issue_result.get("id"),
        "summary": fields["summary"],
        "issue_type": resolved_issue_type,
        "priority": resolved_priority or str(ticket.get("priority") or "").strip(),
        "assignee": resolved_assignee or str(ticket.get("assignee") or "").strip(),
        "labels": fields.get("labels", []),
        "references": _extract_ticket_references(ticket, description),
    }


async def _update_existing_tickets(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: BundleRequest,
    version: ReleaseVersion,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    updated_tickets: list[dict[str, Any]] = []
    for ticket_id in request.existing_ticket_ids:
        err = _jira_check_project_allowed(ticket_id, request.allowed)
        if err:
            return {"error": err}, updated_tickets
        status_code = await _jira_helpers_api._jira_api_put(
            client,
            jira_url,
            f"/issue/{ticket_id}",
            headers=headers,
            payload={"fields": {"fixVersions": version.fix_versions()}},
        )
        updated_tickets.append(
            {
                "ticket_id": ticket_id,
                "status_code": status_code,
                "updated_fields": ["fixVersions"],
            }
        )
    return None, updated_tickets


def _bundle_result(
    request: BundleRequest,
    version: ReleaseVersion,
    *,
    created_tickets: list[dict[str, Any]],
    updated_tickets: list[dict[str, Any]],
    release_status_code: int | None,
) -> dict[str, Any]:
    existing = version.existing
    return {
        "project_key": request.project_key,
        "release_name": version.version_name,
        "version_id": version.version_id,
        "version_created": version.created,
        "release_date": request.release_date
        or (str(existing.get("releaseDate") or "").strip() if isinstance(existing, dict) else ""),
        "release_now": request.release_now,
        "release_status": "released" if request.release_now and release_status_code else "prepared",
        "release_status_code": release_status_code,
        "api_version": version.api_version,
        "created_tickets": created_tickets,
        "created_ticket_count": len(created_tickets),
        "updated_tickets": updated_tickets,
        "updated_ticket_count": len(updated_tickets),
    }


async def run_release_bundle(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], request: BundleRequest
) -> dict[str, Any]:
    cloud_accounts: dict[str, str] = {}
    if request.cloud:
        error, cloud_accounts = await resolve_cloud_accounts(client, jira_url, headers=headers, request=request)
        if error:
            return error
    version = await ensure_release_version(client, jira_url, headers=headers, request=request)

    created_tickets: list[dict[str, Any]] = []
    for ticket in request.tickets:
        if not isinstance(ticket, dict) or not str(ticket.get("summary") or "").strip():
            continue
        created_tickets.append(
            await _create_ticket(
                client, jira_url, headers=headers, request=request, ticket=ticket, version=version,
                cloud_accounts=cloud_accounts,
            )
        )

    error, updated_tickets = await _update_existing_tickets(
        client, jira_url, headers=headers, request=request, version=version
    )
    if error:
        return error
    release_status_code = await release_version(client, jira_url, headers=headers, request=request, version=version)
    return _bundle_result(
        request,
        version,
        created_tickets=created_tickets,
        updated_tickets=updated_tickets,
        release_status_code=release_status_code,
    )


__all__ = ["run_release_bundle"]
