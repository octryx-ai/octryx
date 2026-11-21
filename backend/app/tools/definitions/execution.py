"""Tool definitions for execution domain."""

from __future__ import annotations

import copy

EXECUTION_DEFINITIONS: dict[str, dict] = {
    "run_cli_command": {
        "type": "function",
        "function": {
            "name": "run_cli_command",
            "description": "Run a CLI command in the workspace. Prefer read-only commands in diagnosis mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                    "allow_dirty_workspace": {
                        "type": "boolean",
                        "description": (
                            "Mutating commands are refused while the workspace has "
                            "uncommitted changes. Set true when the dirty state is your "
                            "own intended work for the current change."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    },
    "start_runtime_process": {
        "type": "function",
        "function": {
            "name": "start_runtime_process",
            "description": (
                "Start a long-running workspace process and return a durable process id for later polling. "
                "Use this instead of run_cli_command when the command may exceed a normal request boundary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                    "allow_dirty_workspace": {"type": "boolean"},
                },
                "required": ["command"],
            },
        },
    },
    "poll_runtime_process": {
        "type": "function",
        "function": {
            "name": "poll_runtime_process",
            "description": "Poll a durable runtime process by id and return current status plus bounded output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                },
                "required": ["process_id"],
            },
        },
    },
    "collect_runtime_process": {
        "type": "function",
        "function": {
            "name": "collect_runtime_process",
            "description": "Collect a durable runtime process result, optionally waiting briefly for completion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                    "wait_seconds": {"type": "integer"},
                },
                "required": ["process_id"],
            },
        },
    },
    "cancel_runtime_process": {
        "type": "function",
        "function": {
            "name": "cancel_runtime_process",
            "description": "Cancel a durable runtime process by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                },
                "required": ["process_id"],
            },
        },
    },
    "save_python_script": {
        "type": "function",
        "function": {
            "name": "save_python_script",
            "description": (
                "Save or update a reusable Python script in the database. Prefer this over temporary scripts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "code": {"type": "string"},
                    "arguments_schema": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "is_active": {"type": "boolean"},
                },
                "required": ["name", "purpose", "code"],
            },
        },
    },
    "run_saved_python_script": {
        "type": "function",
        "function": {
            "name": "run_saved_python_script",
            "description": "Execute a saved Python script by id or name. Saved scripts should define main(args).",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_id": {"type": "string"},
                    "name": {"type": "string"},
                    "args": {"type": "object"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": ("Execute a shell command in the workspace. Default cwd: workspace root. Timeout: 120s. "
                            "Builds, tests, installs and repository scripts are refused on the server."),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["command"],
            },
        },
    },
}


def get_execution_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for execution tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(EXECUTION_DEFINITIONS)
