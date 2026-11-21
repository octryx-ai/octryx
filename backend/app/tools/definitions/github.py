"""Tool definitions for github domain."""

from __future__ import annotations

import copy

from .github_issues import GITHUB_ISSUE_DEFINITIONS
from .github_pull_requests import GITHUB_PULL_REQUEST_DEFINITIONS

_GITHUB_REPOSITORY_DEFINITIONS: dict[str, dict] = {
    "list_github_repositories": {
        "type": "function",
        "function": {
            "name": "list_github_repositories",
            "description": "List GitHub repositories visible to the configured connector",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "create_github_repository": {
        "type": "function",
        "function": {
            "name": "create_github_repository",
            "description": "Create a new GitHub repository and optionally bootstrap it into the current workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Repository name"},
                    "owner": {"type": "string", "description": "Optional owner or organization override"},
                    "owner_type": {"type": "string", "description": "org or user"},
                    "visibility": {"type": "string", "description": "private or public"},
                    "default_branch": {"type": "string"},
                    "local_path": {
                        "type": "string",
                        "description": "Optional local path inside the workspace root",
                    },
                    "create_readme": {"type": "boolean"},
                    "create_gitignore": {"type": "boolean"},
                    "initial_commit": {"type": "boolean"},
                    "initial_commit_message": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["name"],
            },
        },
    },
    "read_github_file": {
        "type": "function",
        "function": {
            "name": "read_github_file",
            "description": "Read a file from a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {"type": "string", "description": "Optional branch, tag, or commit"},
                },
                "required": ["repository", "path"],
            },
        },
    },
    "list_github_branches": {
        "type": "function",
        "function": {
            "name": "list_github_branches",
            "description": "List branches for a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["repository"],
            },
        },
    },
    "create_github_branch": {
        "type": "function",
        "function": {
            "name": "create_github_branch",
            "description": "Create a branch in a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "start_point": {"type": "string", "description": "Base branch or commit sha"},
                },
                "required": ["repository", "branch_name"],
            },
        },
    },
    "prepare_github_repository": {
        "type": "function",
        "function": {
            "name": "prepare_github_repository",
            "description": "Clone or update a configured GitHub repository into a local workspace branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "base_branch": {"type": "string"},
                    "branch_name": {"type": "string"},
                },
                "required": ["repository"],
            },
        },
    },
    "commit_and_push_github_repository_branch": {
        "type": "function",
        "function": {
            "name": "commit_and_push_github_repository_branch",
            "description": "Commit local repository changes and push the current GitHub branch to origin",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "local_path": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "message": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "push_only": {"type": "boolean", "description": "Push the branch without a commit (never forced)"},
                },
                "required": ["repository", "local_path", "commit_message"],
            },
        },
    },
    "get_github_commit_checks": {
        "type": "function",
        "function": {
            "name": "get_github_commit_checks",
            "description": "CI results (commit statuses and check runs) of one commit of an allowed GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {"repository": {"type": "string", "description": "owner/repo"},
                               "commit": {"type": "string", "description": "Commit SHA"}},
                "required": ["repository", "commit"],
            },
        },
    },
}


def get_github_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for github tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(
        {
            **_GITHUB_REPOSITORY_DEFINITIONS,
            **GITHUB_PULL_REQUEST_DEFINITIONS,
            **GITHUB_ISSUE_DEFINITIONS,
        }
    )
