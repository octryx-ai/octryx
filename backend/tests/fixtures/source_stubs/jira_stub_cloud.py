"""A Jira **Cloud**-shaped REST stub (API v3), next to the Server/DC stub ``jira_stub.py``.

It answers the Cloud requests the platform's Jira code makes, and refuses every Server/DC-only shape, so a
request that only works on Server/DC fails loudly here instead of passing by accident:

- ``POST /rest/api/3/search/jql`` with ``{jql, fields, maxResults, nextPageToken?}``: explicit ``fields``
  are required, pages continue by an opaque ``nextPageToken`` and end with ``isLast``; no ``total``.
  The withdrawn ``/rest/api/{2,3}/search`` answers 410, as Jira Cloud does;
- ``GET /rest/api/3/user/search?query=`` and ``/rest/api/3/user/assignable/search?project=&query=``:
  people by ``accountId`` only (no ``name``); a ``username`` parameter is a 400;
- ``GET /rest/api/3/issue/{key}`` and ``/comment``: descriptions and comment bodies are ADF documents;
- ``POST /rest/api/3/issue``, ``PUT /rest/api/3/issue/{key}``, ``POST /rest/api/3/issue/{key}/comment``:
  a description or comment that is not an ADF document is a 400, and so is an assignee given by ``name``;
- ``GET /rest/api/3/project/{key}`` and ``/rest/api/3/priority`` for the create/update resolvers;
- ``GET /rest/api/2/project/{key}/version`` (still served on Cloud, paged with ``isLast``) for the release
  listing, and ``fixVersion = <id>`` in a ``search/jql`` query narrows the issues to that version.

401 without the stub's Basic credential, 404 for anything unknown. ``handle`` is pure (the request body is a
parameter), so tests drive it behind an ``httpx.MockTransport``. The credential protects nothing.
"""

from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, urlsplit

CLOUD_EMAIL = "octryx-cloud-sync@stub.octryx.test"
CLOUD_TOKEN = "local-jira-cloud-stub-token-not-a-secret"
PROJECT_KEY = "OPS"
MAX_PAGE_SIZE = 100
_AUTHORIZATION = "Basic " + base64.b64encode(f"{CLOUD_EMAIL}:{CLOUD_TOKEN}".encode()).decode()


def adf(*paragraphs: str) -> dict:
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs],
    }


USERS = [
    {"accountId": "5b10ac8d82e05b22cc7d4ef5", "displayName": "Ada Lovelace", "emailAddress": "ada@example.test",
     "active": True},
    {"accountId": "5b10a2844c20165700ede21g", "displayName": "Alan Turing", "emailAddress": "alan@example.test",
     "active": True},
]
VERSIONS = [{"id": "20001", "name": "2.4.19", "released": True}, {"id": "20002", "name": "2.4.20", "released": False}]
COMMENTS = [
    {"id": "20001", "author": {"accountId": "5b10a2844c20165700ede21g", "displayName": "Alan Turing"},
     "body": adf("Looks good to me."), "created": "2026-10-02T09:00:00.000+0000"},
]
_FIX_VERSION = re.compile(r"fixVersion = (?P<id>\d+)")
ISSUES = [
    {
        "id": str(10000 + number),
        "key": f"{PROJECT_KEY}-{number}",
        "fields": {
            "summary": f"Cloud issue {number}",
            "description": adf(f"First paragraph of {PROJECT_KEY}-{number}.", "Second paragraph."),
            "status": {"name": "To Do"},
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "assignee": {"accountId": USERS[0]["accountId"], "displayName": USERS[0]["displayName"]},
            "created": f"2026-10-0{1 + number % 5}T10:00:00.000+0000",
            "updated": f"2026-10-0{1 + number % 5}T12:00:00.000+0000",
            "fixVersions": [{"id": VERSIONS[number % 2]["id"], "name": VERSIONS[number % 2]["name"]}],
            "comment": {"comments": COMMENTS, "total": len(COMMENTS)},
            "security": None,
        },
    }
    for number in range(1, 8)
]


def _query(target: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(target)
    return parts.path, parse_qs(parts.query, keep_blank_values=True)


def _is_adf(value: object) -> bool:
    return isinstance(value, dict) and value.get("type") == "doc" and value.get("version") == 1


def _search(body: dict | None) -> tuple[int, dict]:
    if not isinstance(body, dict) or not isinstance(body.get("jql"), str):
        return 400, {"errorMessages": ["jql is required"]}
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        return 400, {"errorMessages": ["explicit fields are required (search/jql returns ids only otherwise)"]}
    size = body.get("maxResults", 50)
    if not isinstance(size, int) or not 1 <= size <= MAX_PAGE_SIZE:
        return 400, {"errorMessages": ["bad maxResults"]}
    token = body.get("nextPageToken")
    if token is not None and not (isinstance(token, str) and token.startswith("page-") and token[5:].isdigit()):
        return 400, {"errorMessages": ["invalid nextPageToken"]}
    start = int(token[5:]) if token else 0
    version = _FIX_VERSION.search(body["jql"])
    matching = [
        issue for issue in ISSUES
        if version is None or any(fix["id"] == version.group("id") for fix in issue["fields"]["fixVersions"])
    ]
    issues = [
        {"id": issue["id"], "key": issue["key"],
         "fields": {name: value for name, value in issue["fields"].items() if name in fields}}
        for issue in matching[start : start + size]
    ]
    end = start + len(issues)
    payload: dict = {"issues": issues, "isLast": end >= len(matching)}
    if end < len(matching):
        payload["nextPageToken"] = f"page-{end}"
    return 200, payload


def _users(query: dict[str, list[str]], *, assignable: bool) -> tuple[int, dict | list]:
    if "username" in query:
        return 400, {"errorMessages": ["username is not supported on Jira Cloud; use query"]}
    if assignable and (query.get("project") or [""])[0] != PROJECT_KEY:
        return 404, {"errorMessages": ["project not found"]}
    needle = (query.get("query") or [""])[0].strip().casefold()
    return 200, [
        user for user in USERS
        if not needle or needle in user["displayName"].casefold() or needle in user["emailAddress"].casefold()
        or needle == user["accountId"].casefold()
    ]


def _write_problem(fields: dict) -> str | None:
    if "description" in fields and not _is_adf(fields["description"]):
        return "description must be an ADF document on API v3"
    assignee = fields.get("assignee")
    if isinstance(assignee, dict) and ("name" in assignee or "accountId" not in assignee):
        return "assignee must be given by accountId on Jira Cloud"
    return None


def handle(method: str, target: str, authorization: str | None, body: dict | None = None) -> tuple[int, dict | list]:
    """Answer one request: ``(status, JSON body)``. Pure, so tests can call it without a socket."""
    path, query = _query(target)
    if path == "/healthz":
        return 200, {"status": "ok"}
    if authorization != _AUTHORIZATION:
        return 401, {"errorMessages": ["unauthorized"]}
    if path in {"/rest/api/2/search", "/rest/api/3/search"}:
        return 410, {"errorMessages": ["The requested API has been removed. Please migrate to /rest/api/3/search/jql."]}
    if path == "/rest/api/3/search/jql" and method == "POST":
        return _search(body)
    if method == "GET" and path == "/rest/api/3/user/search":
        return _users(query, assignable=False)
    if method == "GET" and path == "/rest/api/3/user/assignable/search":
        return _users(query, assignable=True)
    if method == "GET" and path == f"/rest/api/3/project/{PROJECT_KEY}":
        return 200, {"key": PROJECT_KEY, "issueTypes": [{"name": "Task", "subtask": False}, {"name": "Bug"}]}
    if method == "GET" and path == f"/rest/api/2/project/{PROJECT_KEY}/version":
        start = int((query.get("startAt") or ["0"])[0])
        size = int((query.get("maxResults") or ["50"])[0])
        window = VERSIONS[start : start + size]
        return 200, {"startAt": start, "maxResults": size, "total": len(VERSIONS),
                     "isLast": start + len(window) >= len(VERSIONS), "values": window}
    if method == "GET" and path == "/rest/api/3/priority":
        return 200, [{"name": "Highest"}, {"name": "Medium"}, {"name": "Low"}]
    if method == "POST" and path == "/rest/api/3/issue":
        fields = (body or {}).get("fields") if isinstance(body, dict) else None
        problem = _write_problem(fields) if isinstance(fields, dict) else "fields are required"
        return (400, {"errorMessages": [problem]}) if problem else (201, {"id": "10100", "key": f"{PROJECT_KEY}-100"})
    if path.startswith("/rest/api/3/issue/"):
        key, _, rest = path.removeprefix("/rest/api/3/issue/").partition("/")
        issue = next((item for item in ISSUES if item["key"] == key), None)
        if issue is None:
            return 404, {"errorMessages": ["Issue does not exist"]}
        if method == "GET" and not rest:
            return 200, issue
        if method == "PUT" and not rest:
            fields = (body or {}).get("fields") if isinstance(body, dict) else None
            problem = _write_problem(fields) if isinstance(fields, dict) else "fields are required"
            return (400, {"errorMessages": [problem]}) if problem else (204, {})
        if rest == "comment" and method == "GET":
            return 200, {"comments": COMMENTS, "total": len(COMMENTS)}
        if rest == "comment" and method == "POST":
            if not _is_adf((body or {}).get("body") if isinstance(body, dict) else None):
                return 400, {"errorMessages": ["comment body must be an ADF document on API v3"]}
            return 201, {"id": "20002"}
    return 404, {"errorMessages": ["not found"]}
