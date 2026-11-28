"""The canonical set of mutating tool names."""

from __future__ import annotations

MUTATING_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "apply_patch",
        "bash",
        "commit_and_push_repository_branch",
        "create_file",
        "delete_file",
        "edit_workspace_file",
        "run_shell_command",
        "write_file",
    }
)
