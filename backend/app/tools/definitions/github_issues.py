"""Tool definitions for GitHub Actions runs and issues."""

from __future__ import annotations

GITHUB_ISSUE_DEFINITIONS: dict[str, dict] = {
    "list_github_action_runs": {
        "type": "function",
        "function": {
            "name": "list_github_action_runs",
            "description": "List GitHub Actions workflow runs for an allowed repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "branch": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["repository"],
            },
        },
    },
    "list_github_issues": {
        "type": "function",
        "function": {
            "name": "list_github_issues",
            "description": "List issues for a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "state": {"type": "string"},
                    "labels": {"type": "string"},
                    "since": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["repository"],
            },
        },
    },
    "get_github_issue": {
        "type": "function",
        "function": {
            "name": "get_github_issue",
            "description": "Get details of a configured GitHub repository issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "issue_number": {"type": "integer"},
                },
                "required": ["repository", "issue_number"],
            },
        },
    },
    "create_github_issue": {
        "type": "function",
        "function": {
            "name": "create_github_issue",
            "description": "Create an issue in a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "assignees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repository", "title"],
            },
        },
    },
    "update_github_issue": {
        "type": "function",
        "function": {
            "name": "update_github_issue",
            "description": "Update title, body, state, labels, or assignees of a configured GitHub issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "issue_number": {"type": "integer"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "state": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "assignees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repository", "issue_number"],
            },
        },
    },
}
