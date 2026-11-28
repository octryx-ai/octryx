"""Jira read results as evidence: every issue and version names its openable source."""

from __future__ import annotations

from typing import Any

from ..evidence_fields import http_url, item_url, with_source


def issue_url(jira_url: str, key: object) -> str | None:
    return item_url(jira_url, "browse", key)


def with_issue_source(item: dict[str, Any], jira_url: str, *, key_field: str = "ticket_id") -> dict[str, Any]:
    key = str(item.get(key_field) or "").strip()
    summary = str(item.get("summary") or "").strip()
    return with_source(item, title=f"{key}: {summary}" if summary else key, url=issue_url(jira_url, key))


def with_version_source(item: dict[str, Any], jira_url: str) -> dict[str, Any]:
    project_key = str(item.get("project_key") or "").strip()
    version_id = str(item.get("id") or "").strip()
    url = item_url(jira_url, "projects", project_key, "versions", version_id) if version_id.isdigit() else None
    return with_source(item, title=f"{project_key} {item.get('name') or version_id}".strip(), url=url)


def with_project_source(item: dict[str, Any], jira_url: str) -> dict[str, Any]:
    key = str(item.get("key") or "").strip()
    return with_source(item, title=item.get("name") or key, url=item_url(jira_url, "browse", key))


def with_board_source(item: dict[str, Any], jira_url: str) -> dict[str, Any]:
    board_id = str(item.get("id") or "").strip()
    url = item_url(jira_url, "secure", "RapidBoard.jspa", query=f"rapidView={board_id}") if board_id.isdigit() else None
    return with_source(item, title=item.get("name") or board_id, url=url)


def with_release_status_sources(result: dict[str, Any]) -> dict[str, Any]:
    project_key = str(result.get("jira_project") or "")
    title = f"{project_key} {result.get('jira_version') or result.get('version') or ''}".strip()
    sourced = with_source(result, title=title, url=http_url(result.get("version_url")))
    blockers = result.get("open_blockers")
    if isinstance(blockers, list):
        sourced["open_blockers"] = [
            with_source(blocker, title=f"{blocker.get('key')}: {blocker.get('summary')}", url=http_url(blocker.get("url")))
            if isinstance(blocker, dict)
            else blocker
            for blocker in blockers
        ]
    return sourced


__all__ = [
    "issue_url",
    "with_board_source",
    "with_issue_source",
    "with_project_source",
    "with_release_status_sources",
    "with_version_source",
]
