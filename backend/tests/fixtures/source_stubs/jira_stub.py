"""A read-only Jira Server/DC REST (API v2) stub for the release acceptance check (K2).

It answers exactly the requests the governed Jira Source Sync connector (``sync/jira.py``,
``sync/jira_releases.py``), the live ``jira_release_status`` (``sync/jira_release_status.py``) and
the admin connection test (``services/connector_test/collab.py``) make, over ``jira_fixtures.py``:

- ``GET /rest/api/2/search?jql=&startAt=&maxResults=&fields=`` for exactly the two JQL shapes the
  platform builds: ``project in ("OPS") ORDER BY created ASC, key ASC`` (the issue sync) and
  ``project = "OPS" AND fixVersion = <id> ORDER BY key ASC`` (release notes and live status). Any
  other JQL is a 400, so a changed query shape fails loudly instead of matching by accident;
- ``GET /rest/api/2/project/{key}/version?startAt=&maxResults=&orderBy=sequence``: the versions,
  paged with ``isLast``;
- ``GET /rest/api/2/myself``: the connection test (``/rest/api/3/myself`` is Cloud-only: 404).

Every other request is refused: 405 for any method but GET, 401 without the stub's Basic
credential, 404 for anything unknown. Served by ``server.py jira`` (``stub_http.py``).
"""

from __future__ import annotations

import re

import jira_fixtures as fixtures
from stub_http import basic_authorization, bounded_int, split_target

MAX_PAGE_SIZE = 1000
_AUTHORIZATION = basic_authorization(fixtures.STUB_USERNAME, fixtures.STUB_TOKEN)
_PROJECT_JQL = re.compile(
    r'^project in \((?P<keys>"[A-Z][A-Z0-9_]*"(?:, "[A-Z][A-Z0-9_]*")*)\) ORDER BY created ASC, key ASC$'
)
_VERSION_JQL = re.compile(r'^project = "(?P<key>[A-Z][A-Z0-9_]*)" AND fixVersion = (?P<version>\d+) ORDER BY key ASC$')


def _issue_number(issue: dict) -> int:
    return int(str(issue["key"]).rsplit("-", 1)[1])


def _matching_issues(jql: str) -> list[dict] | None:
    """The fixture issues of one supported JQL, in its order; ``None`` for an unsupported query."""
    project = _PROJECT_JQL.fullmatch(jql)
    if project:
        keys = {key.strip('"') for key in project.group("keys").split(", ")}
        found = [issue for issue in fixtures.ISSUES if str(issue["key"]).split("-")[0] in keys]
        return sorted(found, key=lambda issue: (issue["fields"]["created"], _issue_number(issue)))
    version = _VERSION_JQL.fullmatch(jql)
    if version:
        found = [
            issue
            for issue in fixtures.ISSUES
            if str(issue["key"]).split("-")[0] == version.group("key")
            and any(fix["id"] == version.group("version") for fix in issue["fields"]["fixVersions"])
        ]
        return sorted(found, key=_issue_number)
    return None


def _search(query: dict[str, list[str]]) -> tuple[int, dict]:
    start, size = bounded_int(query, "startAt", 0), bounded_int(query, "maxResults", 50)
    if start is None or size is None or not 1 <= size <= MAX_PAGE_SIZE:
        return 400, {"errorMessages": ["bad paging"]}
    issues = _matching_issues((query.get("jql") or [""])[0])
    if issues is None:
        return 400, {"errorMessages": ["The stub supports only the JQL shapes the platform builds."]}
    wanted = {name for name in ",".join(query.get("fields") or []).split(",") if name}
    page = [
        {
            "id": issue["id"],
            "key": issue["key"],
            "fields": {name: value for name, value in issue["fields"].items() if not wanted or name in wanted},
        }
        for issue in issues[start : start + size]
    ]
    return 200, {"startAt": start, "maxResults": size, "total": len(issues), "issues": page}


def _versions(project_key: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    if project_key != fixtures.PROJECT_KEY:
        return 404, {"errorMessages": ["No project could be found with key."]}
    start, size = bounded_int(query, "startAt", 0), bounded_int(query, "maxResults", 50)
    if start is None or size is None or not 1 <= size <= MAX_PAGE_SIZE:
        return 400, {"errorMessages": ["bad paging"]}
    values = [{**version, "projectId": fixtures.PROJECT_ID} for version in fixtures.VERSIONS]
    window = values[start : start + size]
    return 200, {
        "startAt": start,
        "maxResults": size,
        "total": len(values),
        "isLast": start + len(window) >= len(values),
        "values": window,
    }


def handle(method: str, target: str, authorization: str | None) -> tuple[int, dict]:
    """Answer one request: ``(status, JSON body)``. Pure, so tests can call it without a socket."""
    path, query = split_target(target)
    if method != "GET":
        return 405, {"errorMessages": ["read-only stub"]}
    if path == "/healthz":
        return 200, {"status": "ok"}
    if authorization != _AUTHORIZATION:
        return 401, {"errorMessages": ["unauthorized"]}
    if path == "/rest/api/2/search":
        return _search(query)
    if path.startswith("/rest/api/2/project/") and path.endswith("/version"):
        return _versions(path.removeprefix("/rest/api/2/project/").removesuffix("/version"), query)
    if path == "/rest/api/2/myself":
        return 200, {"name": "octryx-release-sync", "emailAddress": fixtures.STUB_USERNAME, "active": True}
    return 404, {"errorMessages": ["not found"]}
