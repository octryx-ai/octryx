"""Jira board/sprint list tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_evidence import with_board_source
from ._jira_helpers_context import _jira_allowed_projects, _jira_auth_headers, _jira_base_url, _jira_http


class ListJiraBoards:
    name = "list_jira_boards"
    description = "List Jira boards (Scrum/Kanban) available to the configured user."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip().upper() or None
        allowed = _jira_allowed_projects(context)
        if project_key and allowed and project_key not in allowed:
            project_key = allowed[0] if len(allowed) == 1 else None
        if not project_key and allowed:
            project_key = allowed[0] if len(allowed) == 1 else None

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        query_params: dict[str, Any] = {"maxResults": 50}
        if project_key:
            query_params["projectKeyOrId"] = project_key

        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            data = await _jira_helpers_api._jira_agile_get(client, jira_url, "/board", headers=headers, params=query_params)

        boards = data.get("values", [])
        return {
            # Each board names its page on the configured Jira (evidence fields).
            "boards": [
                with_board_source(
                    {
                        "id": b.get("id"),
                        "name": b.get("name"),
                        "type": b.get("type"),
                        "project_key": (b.get("location") or {}).get("projectKey"),
                    },
                    jira_url,
                )
                for b in boards
            ]
        }


class ListJiraSprints:
    name = "list_jira_sprints"
    description = "List sprints for a Jira board. State filter: active, future, closed (default: active,future)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        board_id = str(params.get("board_id") or "").strip()
        if not board_id:
            return {"error": "board_id is required"}

        state = str(params.get("state") or "active,future").strip()
        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            data = await _jira_helpers_api._jira_agile_get(
                client,
                jira_url,
                f"/board/{board_id}/sprint",
                headers=headers,
                params={"state": state, "maxResults": 50},
            )

        sprints = data.get("values", [])
        return {
            "board_id": board_id,
            "sprints": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "state": s.get("state"),
                    "start_date": s.get("startDate"),
                    "end_date": s.get("endDate"),
                    "complete_date": s.get("completeDate"),
                    "goal": s.get("goal"),
                }
                for s in sprints
            ],
        }
