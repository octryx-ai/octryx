"""The canonical set of mutating tool names.

Phase validation (``workflow_runs/phase_validation``) and instruction conflict checks (``instructions/conflicts``)
read it to tell mutating tools from read-only ones.
"""

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
