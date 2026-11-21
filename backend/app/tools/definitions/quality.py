"""Tool definitions for the code-quality and delivery domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


QUALITY_DEFINITIONS: dict[str, dict] = {
    "run_test_suite": {
        "type": "function",
        "function": {
            "name": "run_test_suite",
            "description": "Run the detected repository test suite and return a structured result",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "framework": {"type": "string"},
                    "path": {"type": "string"},
                    "coverage": {"type": "boolean"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "run_validation_commands": {
        "type": "function",
        "function": {
            "name": "run_validation_commands",
            "description": (
                "Run the approved verification contract of this coding execution "
                "(exact commands, no substitutions) and return per-command results plus all_green"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {
                        "type": "string",
                        "description": "Workspace directory (defaults to the session workspace).",
                    },
                },
            },
        },
    },
    "run_sast_suite": {
        "type": "function",
        "function": {
            "name": "run_sast_suite",
            "description": "Run language-aware SAST checks for the current repository and return structured results",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "runners": {"type": "array", "items": {"type": "string"}},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "run_openrewrite_recipe": {
        "type": "function",
        "function": {
            "name": "run_openrewrite_recipe",
            "description": "Run OpenRewrite recipes for the current Java repository and return structured results",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "recipes": {"type": "array", "items": {"type": "string"}},
                    "recipe_artifacts": {"type": "array", "items": {"type": "string"}},
                    "dry_run": {"type": "boolean"},
                    "export_datatables": {"type": "boolean"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "build_pull_request_description": {
        "type": "function",
        "function": {
            "name": "build_pull_request_description",
            "description": "Build a structured PR description using the project's PR template and validation context",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "project_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "test_results": {"type": "object"},
                    "lint_results": {"type": "object"},
                    "risk_notes": {"type": "array", "items": {"type": "string"}},
                    "days": {"type": "integer"},
                },
            },
        },
    },
    "analyze_codebase_patterns": {
        "type": "function",
        "function": {
            "name": "analyze_codebase_patterns",
            "description": "Extract naming, import, test and error-handling conventions from the current repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "max_files": {"type": "integer"},
                    "project_id": {"type": "string"},
                    "persist": {"type": "boolean"},
                },
            },
        },
    },
    "list_saved_python_scripts": {
        "type": "function",
        "function": {
            "name": "list_saved_python_scripts",
            "description": "List reusable Python scripts stored in the database",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean"},
                },
            },
        },
    },
    "get_saved_python_script": {
        "type": "function",
        "function": {
            "name": "get_saved_python_script",
            "description": "Get metadata for a saved Python script, with code only when required",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_id": {"type": "string"},
                    "name": {"type": "string"},
                    "include_code": {"type": "boolean"},
                },
            },
        },
    },
}


def get_quality_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for quality tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(QUALITY_DEFINITIONS)
