"""Fixture content of the Jira stub, and what the release acceptance check expects from it (K2)."""

from __future__ import annotations

STUB_HOST = "127.0.0.1"
STUB_PORT = 8096
STUB_USERNAME = "octryx-release-sync@stub.octryx.test"
STUB_TOKEN = "local-jira-stub-token-not-a-secret"
PROJECT_KEY = "OPS"
PROJECT_ID = "10000"
PRODUCT = "acme-orders"
RELEASE_QUESTION = "what changes in 2.4.20"

VERSIONS: tuple[dict[str, object], ...] = (
    {
        "id": "20019",
        "name": "2.4.19",
        "released": True,
        "archived": False,
        "releaseDate": "2026-09-15",
        "description": "Maintenance release of the risk dashboard.",
    },
    {
        "id": "20020",
        "name": "2.4.20",
        "released": False,
        "archived": False,
        "releaseDate": "2026-10-15",
        "description": "Payment retries, audit export and checkout fixes.",
    },
)

_CATEGORY = {"To Do": ("new", "To Do"), "In Progress": ("indeterminate", "In Progress"), "Done": ("done", "Done")}


def _issue(number: int, issue_type: str, summary: str, status: str, priority: str, fix: str, **extra) -> dict:
    category_key, category_name = _CATEGORY[status]
    fields: dict[str, object] = {
        "summary": summary,
        "description": f"{summary}. Delivered for the {fix} release of the risk platform.",
        "issuetype": {"name": issue_type},
        "status": {"name": status, "statusCategory": {"key": category_key, "name": category_name}},
        "priority": {"name": priority},
        "resolution": {"name": "Fixed"} if status == "Done" else None,
        "labels": list(extra.get("labels", ())),
        "components": [{"name": "core"}],
        "fixVersions": [{"id": next(str(v["id"]) for v in VERSIONS if v["name"] == fix), "name": fix}],
        "versions": [],
        "created": f"2026-09-{number:02d}T09:00:00.000+0000",
        "updated": f"2026-09-{number:02d}T10:00:00.000+0000",
        "assignee": {"displayName": "Release Engineer"},
        "reporter": {"displayName": "Product Owner"},
        "comment": {"comments": []},
    }
    if extra.get("security"):
        fields["security"] = {"id": "10100", "name": extra["security"]}
    return {"id": str(30000 + number), "key": f"{PROJECT_KEY}-{number}", "fields": fields}


ISSUES: tuple[dict, ...] = (
    _issue(1, "Story", "Payment retry backoff", "Done", "Major", "2.4.20", labels=("payments",)),
    _issue(2, "Bug", "Audit export truncates long lines", "In Progress", "Blocker", "2.4.20"),
    _issue(3, "Task", "Upgrade the logging library", "To Do", "Minor", "2.4.20"),
    _issue(4, "Bug", "Credential rotation leaks a token", "To Do", "Critical", "2.4.20", security="Security team"),
    _issue(5, "Story", "Dashboard dark mode", "Done", "Major", "2.4.19"),
    _issue(6, "Bug", "Checkout crash on an empty cart", "Done", "Blocker", "2.4.20"),
)
SECURED_ISSUES = frozenset({"OPS-4"})

RELEASES: dict[str, object] = {
    "products": {PROJECT_KEY: PRODUCT},
    "sections": [
        {"title": "Fixes", "issue_types": ["Bug"]},
        {"title": "Features", "issue_types": ["Story"]},
    ],
    "blocker_priorities": ["Blocker"],
}

SYNC_OUTCOMES: dict[str, tuple[str, str | None]] = {
    **{issue["id"]: ("created", None) for issue in ISSUES if issue["key"] not in SECURED_ISSUES},
    **{issue["id"]: ("skipped", "restricted_acl") for issue in ISSUES if issue["key"] in SECURED_ISSUES},
    "release-20019": ("created", None),
    "release-20020": ("created", None),
}

RELEASE_TITLE = "Release 2.4.20"
RELEASE_VERSION = "2.4.20"
RELEASE_ISSUES = ("OPS-1", "OPS-2", "OPS-3", "OPS-6")
EXPECTED_STATUS: dict[str, object] = {
    "state": "ok",
    "released": False,
    "release_date": "2026-10-15",
    "issue_count": 4,
    "status_counts": {"to_do": 1, "in_progress": 1, "done": 2, "unknown": 0},
    "open_blockers": ["OPS-2"],
}


def browse_url(base_url: str, key: str) -> str:
    return f"{base_url}/browse/{key}"
