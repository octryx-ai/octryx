"""Steps of ``create_jira_sprint_bundle``: board choice, release with an issue type retry, sprint ticket list."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext


def _is_scrum(board: dict[str, Any]) -> bool:
    return str(board.get("type") or "").strip().lower() == "scrum"


def pick_scrum_board(boards: list[dict[str, Any]], *, board_name: str, project_key: str) -> dict[str, Any] | None:
    """The named board, else the project's sprint scrum board, else its scrum board, else any scrum board."""
    board_name_lower = board_name.casefold()
    if board_name_lower:
        for board in boards:
            if str(board.get("name") or "").strip().casefold() == board_name_lower:
                return board
    for board in boards:
        name = str(board.get("name") or "").strip().casefold()
        if _is_scrum(board) and project_key.casefold() in name and "sprint" in name:
            return board
    for board in boards:
        if _is_scrum(board) and project_key.casefold() in str(board.get("name") or "").strip().casefold():
            return board
    for board in boards:
        if _is_scrum(board):
            return board
    return None


def _asked_for_issue_types(release_bundle_params: dict[str, Any]) -> bool:
    return bool(
        str(release_bundle_params.get("issue_type") or "").strip()
        or any(
            str((ticket or {}).get("issue_type") or "").strip()
            for ticket in (release_bundle_params.get("tickets") or [])
            if isinstance(ticket, dict)
        )
    )


async def create_release_with_issue_type_retry(
    release_bundle_params: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Create the release bundle; a 400 with explicit issue types is retried once with the project default."""
    from ._jira_release_bundle import CreateJiraReleaseBundle

    release_result = await CreateJiraReleaseBundle().execute(release_bundle_params, context)
    if (
        release_result.get("error")
        and "400" in str(release_result.get("error") or "")
        and _asked_for_issue_types(release_bundle_params)
    ):
        relaxed_tickets: list[dict[str, Any]] = []
        for ticket in release_bundle_params.get("tickets") or []:
            if not isinstance(ticket, dict):
                continue
            relaxed_ticket = dict(ticket)
            relaxed_ticket.pop("issue_type", None)
            relaxed_tickets.append(relaxed_ticket)
        relaxed_params = dict(release_bundle_params)
        relaxed_params["issue_type"] = ""
        relaxed_params["tickets"] = relaxed_tickets
        release_result = await CreateJiraReleaseBundle().execute(relaxed_params, context)
    return release_result


def sprint_ticket_ids(release_result: dict[str, Any], params: dict) -> list[str]:
    """Created, updated and explicitly named tickets, each once, in that order."""
    ticket_ids = [
        str(item.get("ticket_id") or "").strip()
        for item in (release_result.get("created_tickets") or [])
        if str(item.get("ticket_id") or "").strip()
    ]
    ticket_ids.extend(
        str(item.get("ticket_id") or "").strip()
        for item in (release_result.get("updated_tickets") or [])
        if str(item.get("ticket_id") or "").strip()
    )
    ticket_ids.extend(str(item).strip() for item in (params.get("ticket_ids") or []) if str(item).strip())
    deduped_ticket_ids: list[str] = []
    seen_ticket_ids: set[str] = set()
    for ticket_id in ticket_ids:
        if ticket_id and ticket_id not in seen_ticket_ids:
            seen_ticket_ids.add(ticket_id)
            deduped_ticket_ids.append(ticket_id)
    return deduped_ticket_ids


def sprint_bundle_result(
    project_key: str,
    *,
    release_result: dict[str, Any],
    sprint_result: dict[str, Any],
    assigned_ticket_ids: list[str],
    sprint_assignment: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "project_key": project_key,
        "release_name": release_result.get("release_name"),
        "release_date": release_result.get("release_date"),
        "version_id": release_result.get("version_id"),
        "release_status": release_result.get("release_status"),
        "sprint_name": sprint_result.get("name"),
        "sprint_id": sprint_result.get("sprint_id"),
        "sprint_state": sprint_result.get("state"),
        "sprint_goal": sprint_result.get("goal"),
        "board_id": sprint_result.get("board_id"),
        "created_tickets": release_result.get("created_tickets") or [],
        "created_ticket_count": int(release_result.get("created_ticket_count") or 0),
        "updated_tickets": release_result.get("updated_tickets") or [],
        "updated_ticket_count": int(release_result.get("updated_ticket_count") or 0),
        "assigned_to_sprint": assigned_ticket_ids,
        "sprint_assignment": sprint_assignment,
        "status": "created",
    }


__all__ = ["create_release_with_issue_type_retry", "pick_scrum_board", "sprint_bundle_result", "sprint_ticket_ids"]
