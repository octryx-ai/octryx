"""Jira sprint tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_helpers_api import _normalize_jira_sprint_datetime
from ._jira_helpers_context import _jira_auth_headers, _jira_base_url, _jira_default_project_key, _jira_http
from ._jira_helpers_ticket import _maybe_block_change_with_approval
from ._jira_sprint_bundle_steps import (
    create_release_with_issue_type_retry,
    pick_scrum_board,
    sprint_bundle_result,
    sprint_ticket_ids,
)


class CreateJiraSprint:
    name = "create_jira_sprint"
    description = "Create or update a Jira sprint on a board, including start/end dates and goal."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        board_id = str(params.get("board_id") or "").strip()
        sprint_name = str(params.get("name") or "").strip()
        return {
            "kind": "jira_sprint",
            "title": "Create Jira sprint",
            "summary": f"{sprint_name or 'Sprint'} on board {board_id or '?'}",
            "after": {
                "board_id": board_id,
                "name": sprint_name,
                "start_date": str(params.get("start_date") or "").strip(),
                "end_date": str(params.get("end_date") or "").strip(),
                "goal": str(params.get("goal") or "").strip(),
            },
            "details": ["The sprint will be created or updated on the selected Jira board."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        board_id = str(params.get("board_id") or "").strip()
        sprint_name = str(params.get("name") or "").strip()
        if not board_id:
            return {"error": "board_id is required"}
        if not sprint_name:
            return {"error": "name is required"}

        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Create Jira sprint {sprint_name}",
        )
        if blocked is not None:
            return blocked

        start_date = _normalize_jira_sprint_datetime(str(params.get("start_date") or "").strip(), end_of_day=False)
        end_date = _normalize_jira_sprint_datetime(str(params.get("end_date") or "").strip(), end_of_day=True)
        goal = str(params.get("goal") or "").strip()

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        payload: dict[str, Any] = {"name": sprint_name}
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date
        if goal:
            payload["goal"] = goal
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            sprint, sprint_created, sprint_status_code = await _upsert_sprint(
                client, jira_url, headers=headers, board_id=board_id, sprint_name=sprint_name, payload=payload
            )

        return {
            "board_id": board_id,
            "sprint_id": sprint.get("id"),
            "name": sprint.get("name") or sprint_name,
            "state": sprint.get("state"),
            "goal": sprint.get("goal") or goal,
            "start_date": sprint.get("startDate") or start_date,
            "end_date": sprint.get("endDate") or end_date,
            "created": sprint_created,
            "status_code": sprint_status_code,
            "status": "created" if sprint_created else "updated",
        }


async def _upsert_sprint(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    board_id: str,
    sprint_name: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool, int]:
    data = await _jira_helpers_api._jira_agile_get(
        client,
        jira_url,
        f"/board/{board_id}/sprint",
        headers=headers,
        params={"state": "active,future", "maxResults": 100},
    )
    existing = None
    for sprint in data.get("values", []) or []:
        if str((sprint or {}).get("name") or "").strip().casefold() == sprint_name.casefold():
            existing = sprint
            break

    if existing is None:
        payload["originBoardId"] = int(board_id)
        sprint_body, sprint_status_code = await _jira_helpers_api._jira_agile_post(
            client,
            jira_url,
            "/sprint",
            headers=headers,
            payload=payload,
        )
        return sprint_body or {}, True, sprint_status_code
    sprint_id = str(existing.get("id") or "").strip()
    sprint_body, sprint_status_code = await _jira_helpers_api._jira_agile_put(
        client,
        jira_url,
        f"/sprint/{sprint_id}",
        headers=headers,
        payload=payload,
    )
    return sprint_body or existing, False, sprint_status_code


class CreateJiraSprintBundle:
    name = "create_jira_sprint_bundle"
    description = (
        "Create or reuse a Jira release, create or update a sprint, create tickets, and assign them to the sprint."
    )

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return {
            "kind": "jira_sprint_bundle",
            "title": "Create Jira sprint bundle",
            "summary": f"{str(params.get('sprint_name') or '').strip() or 'Sprint'} / {str(params.get('release_name') or '').strip() or 'release'}",
            "after": {
                "project_key": str(params.get("project_key") or "").strip(),
                "release_name": str(params.get("release_name") or "").strip(),
                "sprint_name": str(params.get("sprint_name") or "").strip(),
                "ticket_count": len(list(params.get("tickets") or [])),
            },
            "details": ["This will create or update the release and sprint and assign the resulting tickets."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ._jira_board_tools import ListJiraBoards
        from ._jira_sprint_issue_tools import AddIssuesToSprint

        project_key = str(params.get("project_key") or _jira_default_project_key(context) or "").strip().upper()
        if not project_key:
            return {"error": "project_key is required"}

        release_name = str(params.get("release_name") or "").strip()
        sprint_name = str(params.get("sprint_name") or "").strip()
        if not release_name:
            return {"error": "release_name is required"}
        if not sprint_name:
            return {"error": "sprint_name is required"}

        board_id = params.get("board_id")
        board_name = str(params.get("board_name") or "").strip()
        board_id_text = str(board_id or "").strip()

        boards_result = await ListJiraBoards().execute({"project_key": project_key}, context)
        if boards_result.get("error"):
            return boards_result
        boards = list(boards_result.get("boards") or [])
        if not board_id_text:
            preferred_board = pick_scrum_board(boards, board_name=board_name, project_key=project_key)
            if preferred_board is None:
                return {"error": "No suitable Jira scrum board found for sprint planning."}
            board_id_text = str(preferred_board.get("id") or "").strip()

        release_params = _release_bundle_params(params, project_key)
        release_result = await create_release_with_issue_type_retry(release_params, context)
        if release_result.get("error"):
            return release_result

        sprint_result = await CreateJiraSprint().execute(_sprint_params(params, board_id_text, sprint_name), context)
        if sprint_result.get("error"):
            return sprint_result

        deduped_ticket_ids = sprint_ticket_ids(release_result, params)
        sprint_assignment = None
        if deduped_ticket_ids:
            sprint_assignment = await AddIssuesToSprint().execute(
                {"sprint_id": sprint_result.get("sprint_id"), "ticket_ids": deduped_ticket_ids},
                context,
            )
            if sprint_assignment.get("error"):
                return sprint_assignment

        return sprint_bundle_result(
            project_key,
            release_result=release_result,
            sprint_result=sprint_result,
            assigned_ticket_ids=deduped_ticket_ids,
            sprint_assignment=sprint_assignment,
        )


def _release_bundle_params(params: dict, project_key: str) -> dict[str, Any]:
    return {
        "project_key": project_key,
        "release_name": str(params.get("release_name") or "").strip(),
        "description": str(params.get("release_description") or "").strip(),
        "release_date": str(params.get("release_date") or "").strip(),
        "release_now": bool(params.get("release_now", False)),
        "issue_type": str(params.get("issue_type") or "").strip(),
        "ticket_ids": list(params.get("ticket_ids") or []),
        "tickets": list(params.get("tickets") or []),
    }


def _sprint_params(params: dict, board_id_text: str, sprint_name: str) -> dict[str, Any]:
    return {
        "board_id": board_id_text,
        "name": sprint_name,
        "start_date": str(params.get("sprint_start_date") or params.get("start_date") or "").strip(),
        "end_date": str(params.get("sprint_end_date") or params.get("end_date") or "").strip(),
        "goal": str(params.get("sprint_goal") or params.get("goal") or "").strip(),
    }
