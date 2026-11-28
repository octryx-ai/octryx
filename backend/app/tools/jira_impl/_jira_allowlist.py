"""Every Jira issue that is returned, stored, indexed or counted belongs to an allowed project."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


def key_project(key: object) -> str:
    text = str(key or "").strip().upper()
    return text.rsplit("-", 1)[0] if ISSUE_KEY.fullmatch(text) else ""


def _declared_project(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    project = issue.get("project") or fields.get("project")
    if isinstance(project, dict):
        project = project.get("key") or project.get("name")
    explicit = issue.get("project_key") or fields.get("project_key")
    return str(explicit or project or "").strip().upper()


def issue_in_allowlist(issue: object, allowed: Iterable[str] | None) -> bool:
    if allowed is None:
        return True
    if not isinstance(issue, dict):
        return False
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    project = key_project(issue.get("key") or fields.get("key"))
    declared = _declared_project(issue)
    if not project or (declared and declared != project):
        return False
    return project in {str(key).strip().upper() for key in allowed}


def allowed_issues(issues: Iterable[object], allowed: Iterable[str] | None) -> list[dict[str, Any]]:
    keys = None if allowed is None else frozenset(str(key).strip().upper() for key in allowed)
    return [issue for issue in issues if isinstance(issue, dict) and issue_in_allowlist(issue, keys)]


__all__ = ["ISSUE_KEY", "allowed_issues", "issue_in_allowlist", "key_project"]
