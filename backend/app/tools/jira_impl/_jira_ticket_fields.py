"""Issue fields of ``create_jira_ticket`` and ``update_jira_ticket`` as asked, before Jira lookups resolve names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._jira_cloud import rich_text_body
from ._jira_helpers_resolver import DEFAULT_JIRA_ISSUE_TYPE


@dataclass(frozen=True)
class NewTicket:
    """A ticket to create, read from the tool parameters."""

    project_key: str
    summary: str
    issue_type: str
    description: str
    assignee: str
    priority: str
    fix_versions: list[Any]
    sprint_id: Any
    story_points: Any
    labels: list[Any]
    parent: str


def new_ticket(params: dict, *, project_key: str, summary: str) -> NewTicket:
    return NewTicket(
        project_key=project_key,
        summary=summary,
        issue_type=str(params.get("issue_type") or DEFAULT_JIRA_ISSUE_TYPE).strip(),
        description=str(params.get("description") or "").strip(),
        assignee=str(params.get("assignee") or "").strip(),
        priority=str(params.get("priority") or "").strip(),
        fix_versions=params.get("fix_versions") or [],  # list of version names
        sprint_id=params.get("sprint_id"),
        story_points=params.get("story_points"),
        labels=params.get("labels") or [],
        parent=str(params.get("parent_key") or "").strip().upper(),
    )


def create_fields(ticket: NewTicket, *, cloud: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": ticket.project_key},
        "summary": ticket.summary,
        "issuetype": {"name": ticket.issue_type},
    }
    if ticket.description:
        # Jira Cloud v3 takes an ADF description; Server/DC keeps the plain wiki text.
        fields["description"] = rich_text_body(ticket.description, cloud=cloud)
    if ticket.assignee:
        fields["assignee"] = {"name": ticket.assignee}
    if ticket.priority:
        fields["priority"] = {"name": ticket.priority}
    if ticket.fix_versions:
        fields["fixVersions"] = [{"name": v} for v in ticket.fix_versions]
    if ticket.labels:
        fields["labels"] = list(ticket.labels)
    if ticket.parent:
        # A story under its epic. Jira Cloud's one hierarchy field is ``parent``
        # (epics and sub-tasks alike; the old Epic Link field is gone on Cloud). Server/DC takes ``parent`` for a
        # sub-task only: an epic there answers Jira's own error, never a story silently outside its epic.
        fields["parent"] = {"key": ticket.parent}
    if ticket.story_points is not None:
        # customfield_10016 is story points in most Jira configs
        fields["story_points"] = ticket.story_points
        fields["customfield_10016"] = ticket.story_points
    return fields


def update_fields(params: dict, *, cloud: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if params.get("summary"):
        fields["summary"] = str(params["summary"]).strip()
    if params.get("description") is not None:
        fields["description"] = rich_text_body(str(params["description"]), cloud=cloud)
    if params.get("assignee") is not None:
        fields["assignee"] = {"name": str(params["assignee"])} if params["assignee"] else None
    if params.get("priority"):
        fields["priority"] = {"name": str(params["priority"])}
    if params.get("fix_versions") is not None:
        fields["fixVersions"] = [{"name": v} for v in params["fix_versions"]]
    if params.get("labels") is not None:
        fields["labels"] = list(params["labels"])
    if params.get("story_points") is not None:
        fields["customfield_10016"] = params["story_points"]
    return fields


__all__ = ["NewTicket", "create_fields", "new_ticket", "update_fields"]
