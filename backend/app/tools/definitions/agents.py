"""Tool definitions for agents domain."""

from __future__ import annotations

import copy

AGENTS_DEFINITIONS: dict[str, dict] = {
    "spawn_sub_agent": {
        "type": "function",
        "function": {
            "name": "spawn_sub_agent",
            "description": "Spawn one or more sub-agents to work on independent sub-tasks in parallel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sub_tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of independent task descriptions, one per sub-agent.",
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Optional maximum number of child runs to execute concurrently.",
                    },
                    "child_agent_type": {
                        "type": "string",
                        "description": "Optional child mode such as diagnosis, knowledge, or change.",
                    },
                    "inherit_agent_definition": {
                        "type": "boolean",
                        "description": "Whether child sessions should inherit the parent agent definition.",
                    },
                    "child_allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional strict allowlist of tools available to each child.",
                    },
                    "child_runtime_timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 300,
                        "description": "Per-child runtime request timeout in seconds.",
                    },
                    "child_group_timeout_seconds": {
                        "type": "integer",
                        "minimum": 30,
                        "maximum": 10800,
                        "description": "Maximum wall-clock wait for the sub-agent group.",
                    },
                    "min_sources_per_child": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Minimum credible source/evidence count expected per child.",
                    },
                    "resume_prompt": {
                        "type": "string",
                        "description": "Optional prompt appended to the parent when child sessions finish.",
                    },
                },
                "required": ["sub_tasks"],
            },
        },
    },
    "delegate_slices": {
        "type": "function",
        "function": {
            "name": "delegate_slices",
            "description": (
                "Workflow run phases with sub-agents only: hand each slice (key, title, task, the confirmed "
                "tests it must make pass) to a sub-agent with its own worktree branch; at most 5 run at once. "
                "Re-delegate a slice by its key with findings. Sub-agents follow this phase's rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "lowercase letters, digits, dashes"},
                                "title": {"type": "string"},
                                "task": {"type": "string"},
                                "tests": {"type": "array", "items": {"type": "string"}},
                                "findings": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["key"],
                        },
                    },
                },
                "required": ["slices"],
            },
        },
    },
    "merge_slices": {
        "type": "function",
        "function": {
            "name": "merge_slices",
            "description": (
                "Workflow run phases with sub-agents only: merge every finished slice into the run's working "
                "copy. A conflict is reported per slice; re-delegate it with the conflicting files as findings."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
}


def get_agents_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for agents tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(AGENTS_DEFINITIONS)
