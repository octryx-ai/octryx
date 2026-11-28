"""A deterministic Markdown rendering of one Jira issue."""

from __future__ import annotations

from typing import Any

from .....tools.jira_impl._jira_cloud import adf_to_text

MAX_COMMENTS = 50
MAX_FIELD_CHARS = 200
MAX_BODY_CHARS = 60_000

SEARCH_FIELDS = (
    "summary,description,status,issuetype,priority,resolution,assignee,reporter,labels,components,"
    "fixVersions,versions,created,updated,security,comment"
)


def _name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key"):
            if value.get(key):
                return " ".join(str(value[key]).split())[:MAX_FIELD_CHARS]
        return ""
    if value is None:
        return ""
    return " ".join(str(value).split())[:MAX_FIELD_CHARS]


def _names(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return ", ".join(name for name in (_name(value) for value in values) if name)


def _body(value: Any) -> str:
    if isinstance(value, dict):
        value = adf_to_text(value)
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").strip()[:MAX_BODY_CHARS]


def render_issue(key: str, fields: dict[str, Any]) -> str:
    summary = _name(fields.get("summary")) or key
    lines = [f"# {key}: {summary}", ""]
    facts = (
        ("Type", _name(fields.get("issuetype"))),
        ("Status", _name(fields.get("status"))),
        ("Priority", _name(fields.get("priority"))),
        ("Resolution", _name(fields.get("resolution"))),
        ("Assignee", _name(fields.get("assignee"))),
        ("Reporter", _name(fields.get("reporter"))),
        ("Labels", _names(fields.get("labels"))),
        ("Components", _names(fields.get("components"))),
        ("Fix versions", _names(fields.get("fixVersions"))),
        ("Affects versions", _names(fields.get("versions"))),
        ("Created", _name(fields.get("created"))),
    )
    lines.extend(f"- {label}: {value}" for label, value in facts if value)
    description = _body(fields.get("description"))
    if description:
        lines.extend(["", "## Description", "", description])
    comment_block = fields.get("comment")
    comments = comment_block.get("comments") if isinstance(comment_block, dict) else None
    if isinstance(comments, list) and comments:
        lines.extend(["", "## Comments"])
        for comment in comments[-MAX_COMMENTS:]:
            if not isinstance(comment, dict):
                continue
            text = _body(comment.get("body"))
            if not text:
                continue
            author = _name(comment.get("author")) or "unknown"
            lines.extend(["", f"### {author}, {_name(comment.get('created'))}".rstrip(", "), "", text])
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["SEARCH_FIELDS", "render_issue"]
