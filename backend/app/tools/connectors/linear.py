"""Linear connector tools."""

from __future__ import annotations

from typing import Any

from app.services.outbound_egress import CONNECTION_LINEAR

from ..context import ToolContext
from ..evidence_fields import vendor_web_url
from .common import _normalize_string_list, _string, connection_http_json

#: This module's HTTP helpers use the linear egress rule.
_http_json = connection_http_json(CONNECTION_LINEAR)


def _linear_base_url(context: ToolContext) -> str:
    return _string(context.project_config.get("linear_url") or "https://api.linear.app/graphql").rstrip("/")


def _linear_headers(context: ToolContext) -> dict[str, str]:
    token = _string(context.project_config.get("linear_api_key"))
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = token
    return headers


def _linear_allowed_team_ids(context: ToolContext) -> list[str]:
    return _normalize_string_list(
        context.project_config.get("linear_allowed_teams") or context.project_config.get("linear_team_id")
    )


def _resolve_linear_team(context: ToolContext, params: dict[str, Any]) -> str | None:
    team_id = _string(params.get("team_id") or context.project_config.get("linear_team_id"))
    allowed = _linear_allowed_team_ids(context)
    if not team_id and len(allowed) == 1:
        team_id = allowed[0]
    if not team_id:
        return None
    if allowed and team_id not in allowed:
        return None
    return team_id


async def _linear_graphql(context: ToolContext, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = await _http_json(
        "POST",
        _linear_base_url(context),
        headers=_linear_headers(context),
        json_body={"query": query, "variables": variables or {}},
    )
    errors = payload.get("errors") or []
    if errors:
        message = "; ".join(_string(item.get("message")) for item in errors if _string(item.get("message")))
        raise ValueError(message or "Linear request failed")
    return payload.get("data") or {}


LINEAR_PUBLIC_API = "https://api.linear.app/graphql"
# The public API answers with issue URLs on Linear's own web host; a self-configured endpoint has none known.
LINEAR_WEB_HOSTS = frozenset({"linear.app"})


def linear_issue_url(context: ToolContext, url: Any) -> str | None:
    return vendor_web_url(url, LINEAR_WEB_HOSTS) if _linear_base_url(context) == LINEAR_PUBLIC_API else None


def _normalize_linear_issue(item: dict[str, Any]) -> dict[str, Any]:
    state = item.get("state") or {}
    assignee = item.get("assignee") or {}
    return {
        "id": item.get("id"),
        "identifier": item.get("identifier"),
        "url": item.get("url"),
        "title": item.get("title"),
        "description": item.get("description"),
        "priority": item.get("priority"),
        "state": state.get("name"),
        "state_id": state.get("id"),
        "assignee": assignee.get("name"),
        "assignee_id": assignee.get("id"),
    }


class CreateLinearIssueTool:
    name = "create_issue"
    description = "Create a Linear issue in an allowed team."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        team_id = _resolve_linear_team(context, params)
        title = _string(params.get("title"))
        if not team_id:
            return {"error": "team_id is required and must be allowed"}
        if not title:
            return {"error": "title is required"}
        input_payload: dict[str, Any] = {"teamId": team_id, "title": title}
        description = _string(params.get("description"))
        state_id = _string(params.get("state_id"))
        assignee_id = _string(params.get("assignee_id"))
        label_ids = _normalize_string_list(params.get("label_ids"))
        priority = params.get("priority")
        if description:
            input_payload["description"] = description
        if state_id:
            input_payload["stateId"] = state_id
        if assignee_id:
            input_payload["assigneeId"] = assignee_id
        if label_ids:
            input_payload["labelIds"] = label_ids
        if priority is not None and str(priority).strip():
            input_payload["priority"] = priority
        data = await _linear_graphql(
            context,
            """
            mutation LinearIssueCreate($input: IssueCreateInput!) {
              issueCreate(input: $input) {
                success
                issue {
                  id
                  identifier
                  title
                  description
                  priority
                  state { id name }
                  assignee { id name }
                }
              }
            }
            """,
            {"input": input_payload},
        )
        payload = data.get("issueCreate") or {}
        issue = payload.get("issue") or {}
        return {"provider": "linear", "success": bool(payload.get("success")), "issue": _normalize_linear_issue(issue)}


async def _team_refusal(context: ToolContext, issue_id: str) -> str | None:
    """Why an update may not touch this issue: it must belong to an allowed team, like a create or a listing.

    Without this check, update_issue took any issue id the key could reach, so a
    connection limited to one team could change issues of every other team.
    """
    allowed = _linear_allowed_team_ids(context)
    if not allowed:
        return None
    data = await _linear_graphql(context, "query LinearIssueTeam($id: String!) { issue(id: $id) { team { id } } }",
                                 {"id": issue_id})
    team_id = _string(((data.get("issue") or {}).get("team") or {}).get("id"))
    if team_id not in allowed:
        return "issue is not in an allowed team"
    return None


class UpdateLinearIssueTool:
    name = "update_issue"
    description = "Update a Linear issue."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        issue_id = _string(params.get("issue_id") or params.get("id"))
        if not issue_id:
            return {"error": "issue_id is required"}
        input_payload: dict[str, Any] = {}
        for key_in, key_out in (
            ("title", "title"),
            ("description", "description"),
            ("state_id", "stateId"),
            ("assignee_id", "assigneeId"),
        ):
            value = _string(params.get(key_in))
            if value:
                input_payload[key_out] = value
        label_ids = _normalize_string_list(params.get("label_ids"))
        if label_ids:
            input_payload["labelIds"] = label_ids
        priority = params.get("priority")
        if priority is not None and str(priority).strip():
            input_payload["priority"] = priority
        if not input_payload:
            return {"error": "at least one mutable field is required"}
        refusal = await _team_refusal(context, issue_id)
        if refusal:
            return {"error": refusal}
        data = await _linear_graphql(
            context,
            """
            mutation LinearIssueUpdate($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                success
                issue {
                  id
                  identifier
                  title
                  description
                  priority
                  state { id name }
                  assignee { id name }
                }
              }
            }
            """,
            {"id": issue_id, "input": input_payload},
        )
        payload = data.get("issueUpdate") or {}
        issue = payload.get("issue") or {}
        return {"provider": "linear", "success": bool(payload.get("success")), "issue": _normalize_linear_issue(issue)}
