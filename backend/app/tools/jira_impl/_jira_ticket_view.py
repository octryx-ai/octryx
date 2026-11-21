"""The answer of ``get_jira_ticket``: a Jira issue and its comments as evidence-ready fields."""

from __future__ import annotations

from typing import Any

from ..evidence_fields import source_fields
from ._jira_allowlist import key_project
from ._jira_cloud import readable_body
from ._jira_evidence import issue_url

TICKET_FIELDS = (
    "summary,description,status,assignee,reporter,priority,issuetype,created,updated,labels,"
    "components,fixVersions,versions,parent,resolution,duedate,customfield_10016,project"
)


def _scoped_parent(parent: object, allowed: list[str] | None) -> object:
    """A parent of another (not allowed) project becomes a key-less marker (r9 C-1c)."""
    if not allowed or not isinstance(parent, dict) or key_project(parent.get("key")) in allowed:
        return parent
    return {"external": True}


def ticket_view(
    ticket_id: str,
    jira_url: str,
    issue: dict[str, Any],
    comments_payload: dict[str, Any],
    *,
    api_version: str,
    allowed: list[str] | None,
) -> dict[str, Any]:
    fields = issue.get("fields", {})
    comments = comments_payload.get("comments", [])
    reporter_obj = fields.get("reporter") or {}
    # The ticket's /browse page on the configured Jira (evidence fields).
    browse_url = issue_url(jira_url, ticket_id)
    source = source_fields(title=f"{ticket_id}: {fields.get('summary') or ''}", url=browse_url) if browse_url else {}
    return {
        "ticket_id": ticket_id,
        **source,
        "api_version": api_version,
        "summary": fields.get("summary"),
        # Jira Cloud v3 bodies are ADF documents; evidence reads them as text (Server/DC text is unchanged).
        "description": readable_body(fields.get("description")),
        "status": fields.get("status", {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("displayName"),
        "reporter": reporter_obj.get("displayName"),
        "reporter_email": reporter_obj.get("emailAddress"),
        "priority": (fields.get("priority") or {}).get("name"),
        "issue_type": (fields.get("issuetype") or {}).get("name"),
        "labels": fields.get("labels", []),
        "components": fields.get("components", []),
        "fix_versions": fields.get("fixVersions", []),
        "affected_versions": fields.get("versions", []),
        "parent": _scoped_parent(fields.get("parent"), allowed),
        "resolution": (fields.get("resolution") or {}).get("name"),
        "due_date": fields.get("duedate"),
        "story_points": fields.get("customfield_10016"),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "comments": [
            {
                "author": c.get("author", {}).get("displayName"),
                "body": readable_body(c.get("body")),
                "created": c.get("created"),
            }
            for c in comments
        ],
    }


__all__ = ["TICKET_FIELDS", "ticket_view"]
