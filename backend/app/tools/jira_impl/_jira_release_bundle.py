"""Jira release bundle tools."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from ._jira_cloud import is_jira_cloud
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_default_project_key,
    _jira_http,
    _normalize_requested_release_date,
)
from ._jira_helpers_ticket import _maybe_block_change_with_approval
from ._jira_release_bundle_tickets import run_release_bundle
from ._jira_release_bundle_version import BundleRequest


class CreateJiraReleaseBundle:
    name = "create_jira_release_bundle"
    description = (
        "Create or reuse a Jira release/version, create and/or update tickets for it, "
        "and optionally mark the release as released."
    )

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        project_key = str(params.get("project_key") or _jira_default_project_key(context) or "").strip().upper()
        release_name = str(params.get("release_name") or "").strip()
        tickets = params.get("tickets") if isinstance(params.get("tickets"), list) else []
        existing_ticket_ids = [str(item).strip() for item in (params.get("ticket_ids") or []) if str(item).strip()]
        return {
            "kind": "jira_release_bundle",
            "title": "Create Jira release bundle",
            "summary": f"{project_key or 'project'} / {release_name or 'release'}",
            "after": {
                "project_key": project_key,
                "release_name": release_name,
                "release_date": str(params.get("release_date") or "").strip(),
                "release_now": bool(params.get("release_now")),
                "new_ticket_count": len(tickets),
                "existing_ticket_ids": existing_ticket_ids,
            },
            "details": [
                "A Jira release/version will be created or reused.",
                "New tickets will be created with the release as fixVersion.",
                "Existing tickets, if provided, will be updated to reference the release.",
            ],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        project_key = str(params.get("project_key") or _jira_default_project_key(context) or "").strip().upper()
        release_name = str(params.get("release_name") or params.get("name") or "").strip()
        if not project_key or not release_name:
            return {"error": "project_key and release_name are required"}

        allowed = _jira_allowed_projects(context)
        if allowed and project_key not in allowed:
            return {"error": f"Project '{project_key}' is not in the allowed list: {allowed}"}

        issue_type_default = str(params.get("issue_type") or "Improvement").strip() or "Improvement"
        request = BundleRequest(
            project_key=project_key,
            release_name=release_name,
            tickets=params.get("tickets") if isinstance(params.get("tickets"), list) else [],
            existing_ticket_ids=[str(item).strip() for item in (params.get("ticket_ids") or []) if str(item).strip()],
            issue_type_default=issue_type_default,
            release_now=bool(params.get("release_now")),
            release_date=_normalize_requested_release_date(str(params.get("release_date") or "").strip(), context),
            version_description=str(params.get("description") or params.get("release_description") or "").strip(),
            allowed=allowed,
            cloud=is_jira_cloud(jira_url, context.project_config),
        )

        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Create Jira release bundle in {project_key}",
        )
        if blocked is not None:
            return blocked

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            return await run_release_bundle(client, jira_url, headers=headers, request=request)
