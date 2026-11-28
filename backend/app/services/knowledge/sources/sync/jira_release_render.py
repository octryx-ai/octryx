"""A deterministic Markdown rendering of one Jira release (a version and its fixVersion issues)."""

from __future__ import annotations

import re
from typing import Any

from .jira_release_config import ReleaseSection
from .jira_render import _body, _name, _names

MAX_DESCRIPTION_EXCERPT_CHARS = 600
MAX_RELEASE_DESCRIPTION_CHARS = 4000
_ISSUE_NUMBER = re.compile(r"-(\d+)$")


def _issue_order(key: str) -> tuple[str, int]:
    match = _ISSUE_NUMBER.search(key)
    return (key.rsplit("-", 1)[0], int(match.group(1)) if match else 0)


def _excerpt(value: Any) -> str:
    text = " ".join(_body(value).split())
    if len(text) <= MAX_DESCRIPTION_EXCERPT_CHARS:
        return text
    return text[:MAX_DESCRIPTION_EXCERPT_CHARS].rstrip() + " …"


def _section_of(fields: dict[str, Any], sections: tuple[ReleaseSection, ...]) -> str:
    issue_type = _name(fields.get("issuetype")) or "Other"
    labels = tuple(_name(label) for label in fields.get("labels") or [] if _name(label))
    for section in sections:
        if section.matches(issue_type, labels):
            return section.title
    return issue_type


def render_release(
    *,
    base_url: str,
    project_key: str,
    product: str,
    version: str,
    jira_version: dict[str, Any],
    issues: list[tuple[str, dict[str, Any]]],
    sections: tuple[ReleaseSection, ...],
    truncated_at: int | None,
) -> str:
    lines = [f"# Release {version}", ""]
    facts = (
        ("Product", product),
        ("Jira project", project_key),
        ("Jira version", _name(jira_version.get("name"))),
        ("Released", "yes" if jira_version.get("released") is True else "no"),
        ("Release date", _name(jira_version.get("releaseDate"))),
        ("Archived", "yes" if jira_version.get("archived") is True else ""),
        ("Issues", str(len(issues))),
    )
    lines.extend(f"- {label}: {value}" for label, value in facts if value)
    description = _body(jira_version.get("description"))[:MAX_RELEASE_DESCRIPTION_CHARS]
    if description:
        lines.extend(["", "## Release description", "", description])
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, fields in issues:
        grouped.setdefault(_section_of(fields, sections), []).append((key, fields))
    configured = [section.title for section in sections if section.title in grouped]
    by_type = sorted(title for title in grouped if title not in configured)
    for title in [*configured, *by_type]:
        lines.extend(["", f"## {title}"])
        for key, fields in sorted(grouped[title], key=lambda item: _issue_order(item[0])):
            summary = _name(fields.get("summary")) or key
            lines.extend(["", f"### {key}: {summary}", "", f"- Jira: {base_url}/browse/{key}"])
            issue_facts = (
                ("Type", _name(fields.get("issuetype"))),
                ("Resolution", _name(fields.get("resolution"))),
                ("Components", _names(fields.get("components"))),
                ("Labels", ", ".join(_name(label) for label in fields.get("labels") or [] if _name(label))),
            )
            lines.extend(f"- {label}: {value}" for label, value in issue_facts if value)
            excerpt = _excerpt(fields.get("description"))
            if excerpt:
                lines.extend(["", excerpt])
    if truncated_at is not None:
        lines.extend(["", f"Only the first {truncated_at} issues of this release are listed."])
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_release"]
