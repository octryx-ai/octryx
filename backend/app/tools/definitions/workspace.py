"""Tool definitions for workspace domain."""

from __future__ import annotations

import copy

_WORKSPACE_DEFINITIONS: dict[str, dict] = {
    "bootstrap_workspace_repository": {
        "type": "function",
        "function": {
            "name": "bootstrap_workspace_repository",
            "description": "Ensure the workspace is backed by git before code is written, optionally creating a GitHub or Bitbucket remote",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "workspace_select": {
        "type": "function",
        "function": {
            "name": "workspace_select",
            "description": "Select a terraform or opentofu workspace and optionally create it if missing",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "create_if_missing": {"type": "boolean"},
                    "timeout_sec": {"type": "integer"},
                },
            },
            "required": ["workspace"],
        },
    },
    "write_workspace_file": {
        "type": "function",
        "function": {
            "name": "write_workspace_file",
            "description": "Create or overwrite a file inside the workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "ensure_trailing_newline": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "list_workspace_directory": {
        "type": "function",
        "function": {
            "name": "list_workspace_directory",
            "description": "List files and directories inside the local workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "include_hidden": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "read_workspace_file": {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "Read a local UTF-8 text file from the workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    "analyze_workspace_repository": {
        "type": "function",
        "function": {
            "name": "analyze_workspace_repository",
            "description": "Summarize a local repository's structure, build files, README coverage, and module hints",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "module_limit": {"type": "integer"},
                    "build_file_limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    "self_review_workspace_diff": {
        "type": "function",
        "function": {
            "name": "self_review_workspace_diff",
            "description": "Review the current workspace diff for missing tests, secrets, debug leftovers and other pre-PR findings",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "diff": {"type": "string"},
                },
            },
        },
    },
    "lint_and_format_workspace": {
        "type": "function",
        "function": {
            "name": "lint_and_format_workspace",
            "description": "Run linting, formatting and optional SAST checks with structured results",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "auto_fix": {"type": "boolean"},
                    "include_sast": {"type": "boolean"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "edit_workspace_file": {
        "type": "function",
        "function": {
            "name": "edit_workspace_file",
            "description": (
                "Make a targeted find-and-replace edit to a file in the workspace. "
                "Prefer this over write_workspace_file for partial changes. "
                "Uses 5 fallback matching strategies. Response includes unified diff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                    "auto_check": {"type": "boolean", "description": "Run syntax check after edit"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    "multi_edit_workspace_file": {
        "type": "function",
        "function": {
            "name": "multi_edit_workspace_file",
            "description": "Apply multiple sequential find-and-replace edits to a single file in one call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "replace_all": {"type": "boolean"},
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        },
    },
    "glob_workspace_files": {
        "type": "function",
        "function": {
            "name": "glob_workspace_files",
            "description": "Find files in the workspace matching a glob pattern (e.g. '**/*.py'). Returns up to 100 results sorted by mtime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Directory to search in (default: workspace root)"},
                },
                "required": ["pattern"],
            },
        },
    },
    "code_structure_snapshot": {
        "type": "function",
        "function": {
            "name": "code_structure_snapshot",
            "description": (
                "Collect a bounded, deterministic code-structure snapshot from workspace source files: "
                "packages, classes/interfaces/enums with declared fields and methods, and literal "
                "extends/implements/uses relations. WHEN: always call this FIRST before drawing class, "
                "component, or data-model diagrams of a codebase (fetch the repository into the workspace "
                "first if needed) — the snapshot is the only valid structure evidence for create_diagram. "
                "WHEN NOT: never draw code diagrams from memory or invent members that are not in the "
                "snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional workspace-relative directories or files to scan (default: workspace root).",
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional language filter: java, python, typescript, javascript, rust, "
                            "terraform (HCL *.tf infrastructure code)."
                        ),
                    },
                    "max_files": {"type": "integer", "description": "Maximum source files parsed (default 500)."},
                    "max_symbols": {
                        "type": "integer",
                        "description": "Maximum classes/packages kept in the diagram brief (default 60).",
                    },
                },
            },
        },
    },
    "grep_workspace": {
        "type": "function",
        "function": {
            "name": "grep_workspace",
            "description": "Search file contents with a regex pattern. Uses ripgrep if available. Returns file, line number, and matched content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "include": {"type": "string", "description": "File glob filter, e.g. '*.py'"},
                    "case_insensitive": {"type": "boolean"},
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context before/after each match (default: 0)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    "apply_patch_workspace": {
        "type": "function",
        "function": {
            "name": "apply_patch_workspace",
            "description": "Apply a unified diff patch to files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "Unified diff patch text"},
                },
                "required": ["patch"],
            },
        },
    },
    "lsp_workspace_symbols": {
        "type": "function",
        "function": {
            "name": "lsp_workspace_symbols",
            "description": "Search for symbols across the workspace using LSP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {
                        "type": "string",
                        "description": "Any file in the workspace (used to detect language)",
                    },
                },
                "required": ["query", "path"],
            },
        },
    },
}


def get_workspace_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for workspace tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(_WORKSPACE_DEFINITIONS)
