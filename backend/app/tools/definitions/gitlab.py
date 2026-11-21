"""Tool definitions for GitLab connector tools."""

from __future__ import annotations

import copy

_GITLAB_DEFINITIONS: dict[str, dict] = {
    "list_gitlab_projects": {
        "type": "function",
        "function": {
            "name": "list_gitlab_projects",
            "description": "List GitLab projects visible to the configured connector",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "read_gitlab_file": {
        "type": "function",
        "function": {
            "name": "read_gitlab_file",
            "description": "Read a file from a configured GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "path": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["project", "path"],
            },
        },
    },
    "list_gitlab_branches": {
        "type": "function",
        "function": {
            "name": "list_gitlab_branches",
            "description": "List branches for a configured GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "limit": {"type": "integer"},
                },
                "required": ["project"],
            },
        },
    },
    "create_gitlab_branch": {
        "type": "function",
        "function": {
            "name": "create_gitlab_branch",
            "description": "Create a branch in a configured GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "branch_name": {"type": "string"},
                    "start_point": {"type": "string"},
                },
                "required": ["project", "branch_name"],
            },
        },
    },
    "prepare_gitlab_repository": {
        "type": "function",
        "function": {
            "name": "prepare_gitlab_repository",
            "description": "Clone or update a configured GitLab project into a local workspace branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "base_branch": {"type": "string"},
                    "branch_name": {"type": "string"},
                },
                "required": ["project"],
            },
        },
    },
    "commit_and_push_gitlab_repository_branch": {
        "type": "function",
        "function": {
            "name": "commit_and_push_gitlab_repository_branch",
            "description": "Commit local repository changes and push the current GitLab branch to origin",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "local_path": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "message": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "push_only": {"type": "boolean", "description": "Push the branch without a commit (never forced)"},
                },
                "required": ["project", "local_path", "commit_message"],
            },
        },
    },
    "list_gitlab_merge_requests": {
        "type": "function",
        "function": {
            "name": "list_gitlab_merge_requests",
            "description": "List merge requests for a configured GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "state": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["project"],
            },
        },
    },
    "get_gitlab_merge_request": {
        "type": "function",
        "function": {
            "name": "get_gitlab_merge_request",
            "description": "Get details of a configured GitLab merge request",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "mr_iid": {"type": "integer"},
                },
                "required": ["project", "mr_iid"],
            },
        },
    },
    "create_gitlab_merge_request": {
        "type": "function",
        "function": {
            "name": "create_gitlab_merge_request",
            "description": "Create a merge request in a configured GitLab project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
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
                "required": ["project", "title", "from_branch"],
            },
        },
    },
    "update_gitlab_merge_request": {
        "type": "function",
        "function": {
            "name": "update_gitlab_merge_request",
            "description": "Update title, description, target branch, or state of a configured GitLab merge request",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "mr_iid": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "to_branch": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["project", "mr_iid"],
            },
        },
    },
    "list_gitlab_pipelines": {
        "type": "function",
        "function": {
            "name": "list_gitlab_pipelines",
            "description": "List GitLab CI pipelines for a configured project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path or numeric project ID"},
                    "ref": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["project"],
            },
        },
    },
    "get_gitlab_commit_checks": {
        "type": "function",
        "function": {
            "name": "get_gitlab_commit_checks",
            "description": "CI results (pipeline jobs and external commit statuses) of one commit of an allowed GitLab project",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "Project path (group/project)"},
                               "commit": {"type": "string", "description": "Commit SHA"}},
                "required": ["project", "commit"],
            },
        },
    },
    "list_gitlab_merge_request_heads": {
        "type": "function",
        "function": {
            "name": "list_gitlab_merge_request_heads",
            "description": "Every open merge request of an allowed GitLab project with its head commit and branches",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "Project path (group/project)"},
                               "comments_since": {"type": "string", "description": "Also list the notes on the open merge requests created since this ISO 8601 time"},
                               "permissions_for": {"type": "array", "items": {"type": "string"}, "description": "Also return these users' access on the project"}},
                "required": ["project"],
            },
        },
    },
    "post_gitlab_merge_request_review": {
        "type": "function",
        "function": {
            "name": "post_gitlab_merge_request_review",
            "description": "Post a review on a GitLab merge request: summary note, inline discussions, commit status",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project path (group/project)"},
                    "mr_iid": {"type": "string", "description": "The merge request's iid"},
                    "commit": {"type": "string", "description": "The reviewed head commit SHA"},
                    "summary": {"type": "string", "description": "The summary note (markdown), edited in place on every review"},
                    "marker": {"type": "string", "description": "Text that identifies the summary note to edit"},
                    "comments": {
                        "type": "array",
                        "description": "Inline comments on lines of the diff (new side)",
                        "items": {"type": "object", "properties": {
                            "path": {"type": "string"}, "line": {"type": "integer"},
                            "old_line": {"type": "integer", "description": "The old-side line of a CONTEXT line"},
                            "body": {"type": "string"},
                            "line_type": {"type": "string", "description": "ADDED or CONTEXT"}}},
                    },
                    "comment": {"type": "string", "description": "A new note in the merge request's overview (a reply to a command)"},
                    "thread_answers": {
                        "type": "array",
                        "description": "Answers in the discussions of earlier inline comments: a reply, and resolve the discussion",
                        "items": {"type": "object", "properties": {
                            "comment_id": {"type": "string", "description": "The discussion id"},
                            "reply": {"type": "string"}, "resolve": {"type": "boolean"}}},
                    },
                    "commit_status": {
                        "type": "object",
                        "description": "The review status of the commit (name octryx-review)",
                        "properties": {"state": {"type": "string", "description": "pending, success, failure, error"},
                                       "description": {"type": "string"}, "target_url": {"type": "string"}},
                    },
                },
                "required": ["project", "mr_iid", "commit"],
            },
        },
    },
}


def get_gitlab_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(_GITLAB_DEFINITIONS)
