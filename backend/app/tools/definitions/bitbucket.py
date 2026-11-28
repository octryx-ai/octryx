"""Tool definitions for bitbucket domain."""

from __future__ import annotations

import copy

from .bitbucket_pull_requests import BITBUCKET_PULL_REQUEST_DEFINITIONS

_BITBUCKET_REPOSITORY_DEFINITIONS: dict[str, dict] = {
    "list_bitbucket_repositories": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_repositories",
            "description": "List Bitbucket repositories explicitly allowed for the current project",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "search_bitbucket_users": {
        "type": "function",
        "function": {
            "name": "search_bitbucket_users",
            "description": "Search Bitbucket users by username, display name, or email before author-filtered evidence lookup",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Username, display name, or email"},
                    "account_id": {"type": "string",
                                   "description": "Bitbucket Cloud only: the exact Atlassian account id"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    "read_bitbucket_file": {
        "type": "function",
        "function": {
            "name": "read_bitbucket_file",
            "description": "Read a file from an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["project_key", "repo_slug", "path"],
            },
        },
    },
    "list_bitbucket_directory": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_directory",
            "description": "List files and directories inside an allowed Bitbucket repository path",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "list_bitbucket_commits": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_commits",
            "description": "List recent commits for an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {"type": "string"},
                    "author": {"type": "string", "description": "Optional exact or partial author filter"},
                    "author_aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional author aliases such as username, display name, or email",
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "list_recent_bitbucket_commits": {
        "type": "function",
        "function": {
            "name": "list_recent_bitbucket_commits",
            "description": "List commits from allowed Bitbucket repositories within the last N days, optionally across all branches",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer"},
                    "per_repo_limit": {"type": "integer"},
                    "include_all_branches": {"type": "boolean"},
                    "branches": {"type": "array", "items": {"type": "string"}},
                    "author": {"type": "string", "description": "Optional exact or partial author filter"},
                    "author_aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional author aliases such as username, display name, or email",
                    },
                    "include_empty_repositories": {"type": "boolean"},
                },
            },
        },
    },
    "get_bitbucket_commit_changes": {
        "type": "function",
        "function": {
            "name": "get_bitbucket_commit_changes",
            "description": "List changed files for a specific commit in an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "commit_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["project_key", "repo_slug", "commit_id"],
            },
        },
    },
    "prepare_bitbucket_repository": {
        "type": "function",
        "function": {
            "name": "prepare_bitbucket_repository",
            "description": "Clone or update an allowed Bitbucket repository locally, pull the latest base branch, and create a new working branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "base_branch": {"type": "string"},
                    "branch_prefix": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "commit_and_push_repository_branch": {
        "type": "function",
        "function": {
            "name": "commit_and_push_repository_branch",
            "description": "Commit local repository changes and push the current branch to origin",
            "parameters": {
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "push_only": {"type": "boolean", "description": "Push the branch without a commit (never forced)"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["local_path", "commit_message"],
            },
        },
    },
    "list_bitbucket_branches": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_branches",
            "description": "List branches of an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "filter": {"type": "string", "description": "Optional name filter"},
                    "limit": {"type": "integer"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "create_bitbucket_branch": {
        "type": "function",
        "function": {
            "name": "create_bitbucket_branch",
            "description": "Create a new branch in an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "branch_name": {"type": "string", "description": "Name for the new branch"},
                    "start_point": {
                        "type": "string",
                        "description": "Commit SHA or branch to start from (default: repo default branch)",
                    },
                },
                "required": ["project_key", "repo_slug", "branch_name"],
            },
        },
    },
}


def get_bitbucket_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**_BITBUCKET_REPOSITORY_DEFINITIONS, **BITBUCKET_PULL_REQUEST_DEFINITIONS})
