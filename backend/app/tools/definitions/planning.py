"""Tool definitions for planning domain."""

from __future__ import annotations

import copy

PLANNING_DEFINITIONS: dict[str, dict] = {
    "release_context": {
        "type": "function",
        "function": {
            "name": "release_context",
            "description": "Release or roll back the active session context checkpoint so tool calls can continue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_name": {"type": "string", "description": "Optional checkpoint name for validation"},
                    "action": {
                        "type": "string",
                        "enum": ["release", "rollback"],
                        "description": "How to finish the checkpoint",
                    },
                },
            },
        },
    },
    "batch": {
        "type": "function",
        "function": {
            "name": "batch",
            "description": (
                "Execute multiple tools in parallel (up to 25). Each invocation specifies tool_name and params. "
                "Returns results in order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "invocations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {"type": "string"},
                                "params": {"type": "object"},
                            },
                            "required": ["tool_name"],
                        },
                        "maxItems": 25,
                    },
                },
                "required": ["invocations"],
            },
        },
    },
    "plan_exit": {
        "type": "function",
        "function": {
            "name": "plan_exit",
            "description": (
                "Exit plan mode and hand off the completed plan to the execution agent. "
                "Call this when you have finished writing the plan. "
                "Only available in plan agent type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {"type": "string", "description": "The completed plan in markdown format"},
                    "summary": {"type": "string", "description": "One-line summary of what will be done"},
                },
                "required": ["plan"],
            },
        },
    },
}


def get_planning_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(PLANNING_DEFINITIONS)


ORCHESTRATION_DEFINITIONS: dict[str, dict] = {
}


def get_orchestration_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(ORCHESTRATION_DEFINITIONS)
