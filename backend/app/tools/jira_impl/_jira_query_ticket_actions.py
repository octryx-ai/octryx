"""Jira ticket read and workflow tool classes."""

from typing import Any

import httpx

from app.services.ai_marking import marking_facts, with_marker
from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_allowlist import issue_in_allowlist
from ._jira_cloud import is_jira_cloud, rich_text_body
from ._jira_evidence import issue_url
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_check_project_allowed,
    _jira_http,
)
from ._jira_helpers_ticket import _maybe_block_change_with_approval
from ._jira_ticket_view import TICKET_FIELDS, ticket_view


class GetJiraTicket:
    name = "get_jira_ticket"
    description = "Read a Jira ticket for context (status, description, comments)"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        ticket_id = str(params.get("ticket_id") or "").strip()
        if not ticket_id:
            return {"error": "ticket_id is required"}

        allowed = _jira_allowed_projects(context)
        err = _jira_check_project_allowed(ticket_id, allowed)
        if err:
            return {"error": err}

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            issue, api_version = await _jira_helpers_api._jira_api_get(
                client,
                jira_url,
                f"/issue/{ticket_id}",
                headers=headers,
                params={"fields": TICKET_FIELDS},
            )
            # Jira may answer an old key with a moved issue; what came back is checked again
            # (its key's project, and fields.project when present) before anything of it is returned.
            if allowed and not issue_in_allowlist(issue, allowed):
                returned = str((issue or {}).get("key") or ticket_id)
                return {"error": _jira_check_project_allowed(returned, allowed)
                        or f"Ticket '{returned}' is not in the allowed list: {allowed}"}
            comments_payload, _ = await _jira_helpers_api._jira_api_get(
                client,
                jira_url,
                f"/issue/{ticket_id}/comment",
                headers=headers,
                params={"maxResults": 20},
            )

        return ticket_view(ticket_id, jira_url, issue, comments_payload, api_version=api_version, allowed=allowed)


class ListJiraTransitions:
    name = "list_jira_transitions"
    description = "List available Jira workflow transitions for a ticket."

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

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            payload, api_version = await _jira_helpers_api._jira_api_get(
                client,
                jira_url,
                f"/issue/{ticket_id}/transitions",
                headers=headers,
            )

        transitions = payload.get("transitions", [])
        return {
            "ticket_id": ticket_id,
            "api_version": api_version,
            "transitions": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "to_status": ((item.get("to") or {}).get("name")),
                    "to_status_id": ((item.get("to") or {}).get("id")),
                }
                for item in transitions
            ],
        }


async def _transition_id_by_name(
    client: httpx.AsyncClient, jira_url: str, ticket_id: str, transition_name: str, *, headers: dict[str, str]
) -> tuple[dict[str, Any] | None, str]:
    transitions_data, _ = await _jira_helpers_api._jira_api_get(client, jira_url, f"/issue/{ticket_id}/transitions", headers=headers)
    transitions = (transitions_data or {}).get("transitions") or []
    name_lower = transition_name.lower()
    for t in transitions:
        if t.get("name", "").lower() == name_lower:
            return None, str(t["id"])
    available = [t.get("name") for t in transitions]
    return {"error": f"Transition '{transition_name}' not found. Available: {available}"}, ""


async def _comment_body(body: str, context: ToolContext) -> str:
    """The comment as posted: usage block of a governed run appended, then the AI output marker."""
    # Governed coding runs get the platform-owned usage block appended
    # server-side; the model cannot omit or fabricate the run metrics.
    from ...services.secure_work.coding.session_usage_report import (
        append_agent_usage_block_for_governed_session,
    )

    body = await append_agent_usage_block_for_governed_session(
        getattr(context, "db", None),
        getattr(context, "session_id", None),
        body,
    )
    # AI output marking (EU AI Act Art. 50(2)): text level, so it reaches both the ADF and the wiki body.
    return with_marker(body, await marking_facts(context))


class TransitionJiraTicket:
    name = "transition_jira_ticket"
    description = "Move a Jira ticket to another workflow transition."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        ticket_id = str(params.get("ticket_id") or "").strip()
        transition_id = str(params.get("transition_id") or "").strip()
        transition_name = str(params.get("transition_name") or "").strip()
        return {
            "kind": "jira_transition",
            "title": "Jira workflow transition",
            "summary": f"{ticket_id or 'ticket'} -> {transition_name or transition_id or 'transition'}",
            "before": {"ticket_id": ticket_id},
            "after": {"transition_id": transition_id, "transition_name": transition_name},
            "details": ["The ticket workflow state will change to the selected transition."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        ticket_id = str(params.get("ticket_id") or "").strip()
        transition_id = str(params.get("transition_id") or "").strip()
        transition_name = str(params.get("transition_name") or "").strip()

        if not ticket_id:
            return {"error": "ticket_id is required"}
        if not transition_id and not transition_name:
            return {"error": "transition_id or transition_name is required"}

        err = _jira_check_project_allowed(ticket_id, _jira_allowed_projects(context))
        if err:
            return {"error": err}
        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Transition Jira ticket {ticket_id}",
        )
        if blocked is not None:
            return blocked

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            # If only name given, look up the transition ID first
            if not transition_id and transition_name:
                error, transition_id = await _transition_id_by_name(
                    client, jira_url, ticket_id, transition_name, headers=headers
                )
                if error:
                    return error

            _, api_version, status_code = await _jira_helpers_api._jira_api_post(
                client,
                jira_url,
                f"/issue/{ticket_id}/transitions",
                headers=headers,
                payload={"transition": {"id": transition_id}},
            )

        return {
            "ticket_id": ticket_id,
            "api_version": api_version,
            "transition_id": transition_id,
            "transition_name": transition_name or transition_id,
            "status_code": status_code,
            "status": "transitioned",
        }


class AddJiraComment:
    name = "add_jira_comment"
    description = "Add a comment to a Jira ticket."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        ticket_id = str(params.get("ticket_id") or "").strip()
        body = str(params.get("body") or "").strip()
        return {
            "kind": "jira_comment",
            "title": "Add Jira comment",
            "summary": f"Comment on {ticket_id or 'ticket'}",
            "after": {"ticket_id": ticket_id, "body": body},
            "details": ["A new Jira comment will be added exactly as shown below."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        ticket_id = str(params.get("ticket_id") or "").strip()
        body = str(params.get("body") or "").strip()
        if not ticket_id or not body:
            return {"error": "ticket_id and body are required"}

        err = _jira_check_project_allowed(ticket_id, _jira_allowed_projects(context))
        if err:
            return {"error": err}
        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Add Jira comment to {ticket_id}",
        )
        if blocked is not None:
            return blocked

        body = await _comment_body(body, context)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        # Jira Cloud v3 takes an ADF comment body; Server/DC keeps the plain wiki text.
        payload = {"body": rich_text_body(body, cloud=is_jira_cloud(jira_url, context.project_config))}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            response_body, api_version, status_code = await _jira_helpers_api._jira_api_post(
                client,
                jira_url,
                f"/issue/{ticket_id}/comment",
                headers=headers,
                payload=payload,
            )

        return {
            "ticket_id": ticket_id,
            "api_version": api_version,
            "status_code": status_code,
            "comment_id": (response_body or {}).get("id"),
            # The commented issue's real page, so the confirmation links it.
            "url": issue_url(jira_url, ticket_id),
            "status": "comment_added",
        }
