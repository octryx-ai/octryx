"""Tool definitions for Bitbucket pull requests, reviews, build statuses and diffs."""

from __future__ import annotations

BITBUCKET_PULL_REQUEST_DEFINITIONS: dict[str, dict] = {
    "list_bitbucket_pull_requests": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_pull_requests",
            "description": "List pull requests for an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "state": {"type": "string", "description": "OPEN, MERGED, DECLINED, or ALL (default: OPEN)"},
                    "branch": {"type": "string", "description": "Filter by target branch"},
                    "limit": {"type": "integer"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "get_bitbucket_pull_request": {
        "type": "function",
        "function": {
            "name": "get_bitbucket_pull_request",
            "description": "Get details of a Bitbucket pull request including diff stat and comments",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "pr_id": {"type": "integer", "description": "Pull request ID"},
                },
                "required": ["project_key", "repo_slug", "pr_id"],
            },
        },
    },
    "create_bitbucket_pull_request": {
        "type": "function",
        "function": {
            "name": "create_bitbucket_pull_request",
            "description": "Create a new pull request in an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "title": {"type": "string"},
                    "from_branch": {"type": "string", "description": "Source branch"},
                    "to_branch": {"type": "string", "description": "Target branch (default: repo default branch)"},
                    "description": {"type": "string"},
                    "requester": {
                        "type": "string",
                        "description": "The reviewer who requested the change; when the connection signs in as them (the author), they are mentioned instead",
                    },
                    "reviewers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Bitbucket usernames to add as reviewers",
                    },
                },
                "required": ["project_key", "repo_slug", "title", "from_branch"],
            },
        },
    },
    "list_bitbucket_pull_request_heads": {
        "type": "function",
        "function": {
            "name": "list_bitbucket_pull_request_heads",
            "description": "Every open pull request of an allowed Bitbucket repository with its head commit and branches",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key (Bitbucket Cloud: workspace)"},
                    "repo_slug": {"type": "string"},
                    "comments_since": {"type": "string", "description": "Also list the comments on the open pull requests created since this ISO 8601 time"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "post_bitbucket_pull_request_review": {
        "type": "function",
        "function": {
            "name": "post_bitbucket_pull_request_review",
            "description": "Post a review on a Bitbucket pull request: summary comment, inline comments, build status",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key (Bitbucket Cloud: workspace)"},
                    "repo_slug": {"type": "string"},
                    "pr_id": {"type": "integer", "description": "Pull request ID"},
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
                "required": ["project_key", "repo_slug", "pr_id", "commit"],
            },
        },
    },
    "add_bitbucket_pull_request_comment": {
        "type": "function",
        "function": {
            "name": "add_bitbucket_pull_request_comment",
            "description": "Comment on a pull request of an allowed Bitbucket repository, named by id or by its source branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key (Bitbucket Cloud: workspace)"},
                    "repo_slug": {"type": "string"},
                    "pr_id": {"type": "integer", "description": "Pull request ID"},
                    "from_branch": {"type": "string", "description": "Source branch of an open pull request"},
                    "text": {"type": "string", "description": "Comment text (markdown on Bitbucket Cloud)"},
                },
                "required": ["project_key", "repo_slug", "text"],
            },
        },
    },
    "get_bitbucket_build_statuses": {
        "type": "function",
        "function": {
            "name": "get_bitbucket_build_statuses",
            "description": "Build statuses (CI, e.g. Bitbucket Pipelines) of a commit or of a branch's head commit",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Project key (Bitbucket Cloud: workspace)"},
                    "repo_slug": {"type": "string"},
                    "commit": {"type": "string", "description": "Commit SHA"},
                    "branch": {"type": "string", "description": "Branch whose head commit is read"},
                    "include_test_reports": {"type": "boolean", "description": "Bitbucket Cloud: also the "
                                             "per-test results of each Pipelines build"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
    "update_bitbucket_pull_request": {
        "type": "function",
        "function": {
            "name": "update_bitbucket_pull_request",
            "description": "Update title, description, target branch, or reviewers of an allowed Bitbucket pull request",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "pr_id": {"type": "integer", "description": "Pull request ID"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "to_branch": {"type": "string", "description": "Updated target branch"},
                    "reviewers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Bitbucket usernames to set as reviewers",
                    },
                },
                "required": ["project_key", "repo_slug", "pr_id"],
            },
        },
    },
    "get_bitbucket_diff": {
        "type": "function",
        "function": {
            "name": "get_bitbucket_diff",
            "description": "Get diff content of a commit or between two refs in an allowed Bitbucket repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "repo_slug": {"type": "string"},
                    "commit_id": {"type": "string", "description": "Single commit SHA for its diff"},
                    "from_ref": {"type": "string", "description": "Start commit/branch for a range diff"},
                    "to_ref": {"type": "string", "description": "End commit/branch for a range diff"},
                    "path": {"type": "string", "description": "Optional file path filter"},
                },
                "required": ["project_key", "repo_slug"],
            },
        },
    },
}
