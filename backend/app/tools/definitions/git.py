"""Tool definitions for git domain."""

from __future__ import annotations

import copy

_GIT_DEFINITIONS: dict[str, dict] = {
    "get_git_diff": {
        "type": "function",
        "function": {
            "name": "get_git_diff",
            "description": "Show git diff in the local workspace repository (working tree, staged, or between commits/branches)",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_ref": {"type": "string", "description": "Start commit or branch"},
                    "to_ref": {"type": "string", "description": "End commit or branch"},
                    "path": {"type": "string", "description": "Restrict diff to this file/directory"},
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged (--cached) changes instead of working tree",
                    },
                    "stat_only": {"type": "boolean", "description": "Show only file change summary, not full diff"},
                    "cwd": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "Max characters of diff output (default 8000)"},
                },
            },
        },
    },
    "list_workspace_git_commits": {
        "type": "function",
        "function": {
            "name": "list_workspace_git_commits",
            "description": "List recent commits from the local workspace git repository using a computed time range",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "cwd": {"type": "string"},
                    "path": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "git_file_intelligence": {
        "type": "function",
        "function": {
            "name": "git_file_intelligence",
            "description": "Return compressed git ownership and co-change signals for a single file",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "file": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": ["file"],
            },
        },
    },
    "git_coupling_map": {
        "type": "function",
        "function": {
            "name": "git_coupling_map",
            "description": "Analyze which files usually change together to catch incomplete changes before commit",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "threshold": {"type": "number"},
                },
                "required": ["changed_files"],
            },
        },
    },
    "git_change_summary": {
        "type": "function",
        "function": {
            "name": "git_change_summary",
            "description": "Summarize recent git history into bug-fix, refactor and feature buckets",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "days": {"type": "integer"},
                },
            },
        },
    },
    "git_function_blame": {
        "type": "function",
        "function": {
            "name": "git_function_blame",
            "description": "Return ownership and commit context for a single function, method or symbol",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "file": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["file", "symbol"],
            },
        },
    },
    "git_conflict_predictor": {
        "type": "function",
        "function": {
            "name": "git_conflict_predictor",
            "description": "Predict whether a planned change is incomplete or likely to collide with active work",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "planned_files": {"type": "array", "items": {"type": "string"}},
                    "open_pull_requests": {"type": "array", "items": {"type": "object"}},
                    "threshold": {"type": "number"},
                },
                "required": ["planned_files"],
            },
        },
    },
    "git_hotspot_analysis": {
        "type": "function",
        "function": {
            "name": "git_hotspot_analysis",
            "description": "Highlight frequently changing risky files in the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "days": {"type": "integer"},
                    "top_n": {"type": "integer"},
                },
            },
        },
    },
    "git_pr_context": {
        "type": "function",
        "function": {
            "name": "git_pr_context",
            "description": "Build a complete PR context from recent history, coupling, hotspots and optional PR metadata",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "pull_request": {"type": "object"},
                    "days": {"type": "integer"},
                },
                "required": ["changed_files"],
            },
        },
    },
    "worktree_create": {
        "type": "function",
        "function": {
            "name": "worktree_create",
            "description": "Create an isolated git worktree for this session. All edits happen in isolation from main branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch_prefix": {"type": "string", "description": "Branch name prefix (default: agent)"},
                },
            },
        },
    },
    "worktree_list": {
        "type": "function",
        "function": {
            "name": "worktree_list",
            "description": "List all active git worktrees managed by this server.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "worktree_diff": {
        "type": "function",
        "function": {
            "name": "worktree_diff",
            "description": "Show all changes in the current session's worktree vs the base commit.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "worktree_commit": {
        "type": "function",
        "function": {
            "name": "worktree_commit",
            "description": "Stage and commit all changes in the current session's worktree.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
            },
        },
    },
    "worktree_cleanup": {
        "type": "function",
        "function": {
            "name": "worktree_cleanup",
            "description": "Remove the git worktree and branch for the current session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "worktree_merge": {
        "type": "function",
        "function": {
            "name": "worktree_merge",
            "description": "Merge the current session's worktree branch into a target branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_branch": {"type": "string", "description": "Branch to merge into (default: main)"},
                },
            },
        },
    },
}


def get_git_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for git tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(_GIT_DEFINITIONS)
