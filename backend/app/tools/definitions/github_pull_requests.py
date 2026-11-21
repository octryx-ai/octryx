"""Tool definitions for GitHub pull requests and reviews."""

from __future__ import annotations

GITHUB_PULL_REQUEST_DEFINITIONS: dict[str, dict] = {
    "list_github_pull_request_heads": {
        "type": "function",
        "function": {
            "name": "list_github_pull_request_heads",
            "description": "Every open pull request of an allowed GitHub repository with its head commit and branches",
            "parameters": {
                "type": "object",
                "properties": {"repository": {"type": "string", "description": "owner/repo"},
                               "comments_since": {"type": "string", "description": "Also list the comments on the open pull requests created or edited since this ISO 8601 time"},
                               "permissions_for": {"type": "array", "items": {"type": "string"}, "description": "Also return these users' permission on the repository"}},
                "required": ["repository"],
            },
        },
    },
    "post_github_pull_request_review": {
        "type": "function",
        "function": {
            "name": "post_github_pull_request_review",
            "description": "Post a review on a GitHub pull request: summary comment, inline comments, commit status",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "pr_number": {"type": "string"},
                    "commit": {"type": "string", "description": "The reviewed head commit SHA"},
                    "summary": {"type": "string", "description": "The summary comment (markdown), edited in place on every review"},
                    "marker": {"type": "string", "description": "Text that identifies the summary comment to edit"},
                    "comments": {
                        "type": "array",
                        "description": "Inline comments on lines of the diff (new side)",
                        "items": {"type": "object", "properties": {
                            "path": {"type": "string"}, "line": {"type": "integer"},
                            "start_line": {"type": "integer"}, "body": {"type": "string"},
                            "line_type": {"type": "string", "description": "ADDED or CONTEXT"}}},
                    },
                    "comment": {"type": "string", "description": "A new comment in the pull request's conversation (a reply to a command)"},
                    "thread_answers": {
                        "type": "array",
                        "description": "Answers in the threads of earlier inline comments: a reply, and resolve the thread",
                        "items": {"type": "object", "properties": {
                            "comment_id": {"type": "string"}, "reply": {"type": "string"},
                            "resolve": {"type": "boolean"}}},
                    },
                    "commit_status": {
                        "type": "object",
                        "description": "The review status of the commit",
                        "properties": {"state": {"type": "string", "description": "pending, success, failure, error"},
                                       "description": {"type": "string"}, "target_url": {"type": "string"}},
                    },
                },
                "required": ["repository", "pr_number", "commit"],
            },
        },
    },
    "list_github_pull_requests": {
        "type": "function",
        "function": {
            "name": "list_github_pull_requests",
            "description": "List pull requests for an allowed GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "state": {"type": "string", "description": "open, closed, all"},
                    "limit": {"type": "integer"},
                },
                "required": ["repository"],
            },
        },
    },
    "get_github_pull_request": {
        "type": "function",
        "function": {
            "name": "get_github_pull_request",
            "description": "Get details of a configured GitHub repository pull request",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["repository", "pr_number"],
            },
        },
    },
    "create_github_pull_request": {
        "type": "function",
        "function": {
            "name": "create_github_pull_request",
            "description": "Create a pull request in a configured GitHub repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "title": {"type": "string"},
                    "from_branch": {"type": "string"},
                    "to_branch": {"type": "string"},
                    "description": {"type": "string"},
                    "requester": {
                        "type": "string",
                        "description": "The reviewer who requested the change; when the connection signs in as them (the author), they are mentioned instead",
                    },
                    "reviewers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Usernames to request as reviewers",
                    },
                },
                "required": ["repository", "title", "from_branch"],
            },
        },
    },
    "update_github_pull_request": {
        "type": "function",
        "function": {
            "name": "update_github_pull_request",
            "description": "Update title, body, base branch, or state of a configured GitHub pull request",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string", "description": "owner/repo"},
                    "owner": {"type": "string"},
                    "pr_number": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "to_branch": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["repository", "pr_number"],
            },
        },
    },
}
