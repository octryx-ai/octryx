"""Final report for the Jira Sprint Planner's release/sprint bundle."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt


def _is_jira_sprint_planner(agent_definition: dict[str, Any] | None) -> bool:
    name = str((agent_definition or {}).get("name") or "").strip()
    return name == "Jira Sprint Planner"


def _text(result: dict[str, Any], key: str) -> str:
    return str(result.get(key) or "").strip()


def _release_line(result: dict[str, Any]) -> str:
    release_name = _text(result, "release_name")
    release_date = _text(result, "release_date")
    version_id = _text(result, "version_id")
    release_line = (
        render_prompt("answer.jira_bundle.release", release_name=release_name)
        if release_name
        else render_prompt("answer.jira_bundle.release_prepared")
    )
    if version_id:
        release_line += render_prompt("answer.jira_bundle.release_version", version_id=version_id)
    if release_date:
        release_line += render_prompt("answer.jira_bundle.release_date", release_date=release_date)
    return release_line


def _sprint_line(result: dict[str, Any]) -> str:
    sprint_name = _text(result, "sprint_name")
    sprint_id = _text(result, "sprint_id")
    board_id = _text(result, "board_id")
    sprint_line = (
        render_prompt("answer.jira_bundle.sprint", sprint_name=sprint_name)
        if sprint_name
        else render_prompt("answer.jira_bundle.sprint_prepared")
    )
    if sprint_id:
        sprint_line += render_prompt("answer.jira_bundle.sprint_id", sprint_id=sprint_id)
    if board_id:
        sprint_line += render_prompt("answer.jira_bundle.sprint_board", board_id=board_id)
    return sprint_line


def _assignee_and_references(created_tickets: list[dict[str, Any]]) -> tuple[str, list[str]]:
    assignee = ""
    references: list[str] = []
    for ticket in created_tickets:
        assignee = assignee or str(ticket.get("assignee") or "").strip()
        for reference in ticket.get("references") or []:
            value = str(reference).strip()
            if value and value not in references:
                references.append(value)
    return assignee, references


def _created_ticket_lines(created_tickets: list[dict[str, Any]]) -> list[str]:
    lines = [render_prompt("answer.jira_bundle.created_header")]
    for ticket in created_tickets[:8]:
        ticket_id = str(ticket.get("ticket_id") or "").strip()
        summary = str(ticket.get("summary") or "").strip()
        priority = str(ticket.get("priority") or "").strip()
        issue_type = str(ticket.get("issue_type") or "").strip()
        parts = [part for part in (summary, priority, issue_type) if part]
        suffix = f" — {' / '.join(parts)}" if parts else ""
        lines.append(f"- `{ticket_id}`{suffix}")
    return lines


def _ticket_list_lines(updated_tickets: list[dict[str, Any]], assigned: list[str]) -> list[str]:
    lines: list[str] = []
    if updated_tickets:
        ids = [
            str(item.get("ticket_id") or "").strip()
            for item in updated_tickets
            if str(item.get("ticket_id") or "").strip()
        ]
        if ids:
            lines.append(
                render_prompt(
                    "answer.jira_bundle.updated", ticket_ids=", ".join(f"`{ticket_id}`" for ticket_id in ids[:12])
                )
            )
    if assigned:
        lines.append(
            render_prompt(
                "answer.jira_bundle.assigned", ticket_ids=", ".join(f"`{ticket_id}`" for ticket_id in assigned[:12])
            )
        )
    return lines


def _build_jira_sprint_bundle_report(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    project_key = _text(result, "project_key")
    assigned = [str(item).strip() for item in (result.get("assigned_to_sprint") or []) if str(item).strip()]
    created_tickets = [item for item in (result.get("created_tickets") or []) if isinstance(item, dict)]
    updated_tickets = [item for item in (result.get("updated_tickets") or []) if isinstance(item, dict)]
    assignee, references = _assignee_and_references(created_tickets)
    lines: list[str] = []
    if project_key:
        lines.append(render_prompt("answer.jira_bundle.project", project_key=project_key))
    lines.append(_release_line(result))
    lines.append(_sprint_line(result))
    if assignee:
        lines.append(render_prompt("answer.jira_bundle.assignee", assignee=assignee))
    if created_tickets:
        lines.extend(_created_ticket_lines(created_tickets))
    lines.extend(_ticket_list_lines(updated_tickets, assigned))
    if references:
        lines.append(render_prompt("answer.jira_bundle.references_header"))
        for reference in references[:6]:
            lines.append(f"- {reference}")
    return "\n".join(lines).strip()


__all__ = ["_build_jira_sprint_bundle_report", "_is_jira_sprint_planner"]
