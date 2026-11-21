"""The shared Jira issue payload builder for the test_secure_work_jira_sync_* modules."""


def _issue(
    key: str,
    *,
    summary: str,
    project_key: str = "OCX",
    status: str = "To Do",
    assignee: str = "alice",
    assignee_display: str = "Alice Example",
    labels: list[str] | None = None,
    fix_versions: list[str] | None = None,
    sprint: dict | None = None,
    updated: str = "2026-06-20T10:00:00Z",
) -> dict:
    return {
        "id": f"id-{key}",
        "key": key,
        "self": f"https://jira.example.test/rest/api/2/issue/{key}",
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": f"Description for {key}",
            "issuetype": {"name": "Story"},
            "status": {"name": status},
            "priority": {"name": "High"},
            "assignee": {"name": assignee, "displayName": assignee_display},
            "reporter": {"emailAddress": "owner@example.test"},
            "watcher": {
                "watchers": [
                    {"name": "reviewer-a"},
                    {"emailAddress": "reviewer-b@example.test"},
                ]
            },
            "labels": labels or ["secure-work", "acme-orders"],
            "components": [{"name": "Backend"}],
            "fixVersions": [{"name": value} for value in (fix_versions or ["2026.06"])],
            "sprint": sprint or {"id": 42, "name": "Sprint 42", "state": "active"},
            "board": {"id": 7, "name": "Risk Board"},
            "team": {"name": "Acme Orders"},
            "parent": {"key": "OCX-1"},
            "customfield_10008": "OCX-EPIC",
            "issuelinks": [{"type": {"name": "blocks"}, "outwardIssue": {"key": "OCX-99"}}],
            "created": "2026-06-19T09:00:00Z",
            "updated": updated,
        },
    }
