"""In-memory Jira Server/DC REST (API v2) stub for workflow-run acceptance tests; state lives in :data:`ISSUES`
until :func:`reset`, and API v3 paths answer 404."""

from __future__ import annotations

import json
import re

import jira_fixtures as fixtures
from stub_http import basic_authorization, split_target

_AUTHORIZATION = basic_authorization(fixtures.STUB_USERNAME, fixtures.STUB_TOKEN)
ISSUE_TYPES = [{"id": "1", "name": "Bug", "subtask": False}, {"id": "2", "name": "Task", "subtask": False},
               {"id": "3", "name": "Story", "subtask": False}]
ISSUES: dict[str, dict] = {}
_ISSUE = re.compile(r"^/rest/api/2/issue/(?P<key>[A-Z][A-Z0-9_]*-\d+)(?P<rest>/comment)?$")


def reset() -> None:
    ISSUES.clear()


def _body(raw: bytes | None) -> dict:
    try:
        value = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def handle(method: str, target: str, authorization: str | None, body: bytes | None = None) -> tuple[int, dict]:
    path, _query = split_target(target)
    if path.startswith("/rest/api/3/"):
        return 404, {"errorMessages": ["Server/DC: API v2 only"]}
    if authorization != _AUTHORIZATION:
        return 401, {"errorMessages": ["unauthorized"]}
    if method == "GET" and path.startswith("/rest/api/2/project/"):
        return 200, {"key": path.rsplit("/", 1)[-1], "issueTypes": ISSUE_TYPES}
    if method == "POST" and path == "/rest/api/2/issue":
        fields = dict(_body(body).get("fields") or {})
        project = str(dict(fields.get("project") or {}).get("key") or "")
        if not project or not fields.get("summary"):
            return 400, {"errorMessages": ["project and summary are required"]}
        key = f"{project}-{100 + sum(1 for item in ISSUES if item.startswith(project + '-'))}"
        ISSUES[key] = {"key": key, "fields": {**fields, "status": {"name": "Open"}}, "comments": []}
        return 201, {"id": str(len(ISSUES)), "key": key}
    match = _ISSUE.match(path)
    if match is None or match["key"] not in ISSUES:
        return 404, {"errorMessages": ["not found"]}
    issue = ISSUES[match["key"]]
    if match["rest"] and method == "POST":
        comment = {"id": str(len(issue["comments"]) + 1), "body": _body(body).get("body")}
        issue["comments"].append(comment)
        return 201, comment
    if not match["rest"] and method == "GET":
        return 200, {"key": issue["key"], "fields": issue["fields"]}
    return 405, {"errorMessages": ["unsupported"]}
