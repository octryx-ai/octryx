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
    """Return OpenAI-compatible tool definitions for planning tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(PLANNING_DEFINITIONS)


ORCHESTRATION_DEFINITIONS: dict[str, dict] = {
    "start_orchestrator": {
        "type": "function",
        "function": {
            "name": "start_orchestrator",
            "description": (
                "Start a new orchestrator run that coordinates one or more child agents. "
                "Use this when a task is complex enough to benefit from a supervisor, "
                "sequential, parallel, reviewer/critic, or evaluator-optimizer pattern. "
                "The orchestrator handles planning, delegation, monitoring, merging, "
                "and conflict resolution automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "enum": [
                            "single",
                            "supervisor",
                            "sequential",
                            "parallel",
                            "reviewer_critic",
                            "evaluator_optimizer",
                        ],
                        "description": (
                            "Orchestration pattern: "
                            "single (one agent, no coordination), "
                            "supervisor (plan→delegate→monitor→merge→resolve→escalate→close), "
                            "sequential (children run one after another), "
                            "parallel (children run concurrently), "
                            "reviewer_critic (critic scores output, agent revises on failure), "
                            "evaluator_optimizer (evaluator scores, agent revises until score passes or "
                            "max_iterations)."
                        ),
                    },
                    "total_steps": {
                        "type": "integer",
                        "description": "Total number of steps or child agents in sequential/parallel patterns.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Max revision iterations for reviewer_critic or evaluator_optimizer patterns.",
                    },
                    "routing_policy": {
                        "type": "object",
                        "description": "Policy for how to route tasks to child agents (criteria, priority rules).",
                    },
                    "delegation_policy": {
                        "type": "object",
                        "description": "Policy for how to delegate tasks (selection criteria, constraints).",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    "complete_orchestrator": {
        "type": "function",
        "function": {
            "name": "complete_orchestrator",
            "description": (
                "Mark the orchestrator run as completed and return the final merged output. "
                "Call this after all steps are done and outputs are merged. "
                "This is the terminal step for the orchestrator pattern."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "The orchestrator run ID.",
                    },
                    "final_output": {
                        "type": "object",
                        "description": "The final merged output from all child agents.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-line summary of what the orchestrator produced.",
                    },
                },
                "required": ["run_id"],
            },
        },
    },
}


def get_orchestration_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for orchestration pattern tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(ORCHESTRATION_DEFINITIONS)
