"""``propose_write_plan``: a chat's one confirmation per request."""

from __future__ import annotations

_SCOPE_KINDS = ["jira_project", "jira_issue", "confluence_space", "confluence_page", "repository", "branch",
                "pull_request", "work_item", "recipient", "run", "target"]


def get_write_plan_definitions() -> dict[str, dict]:
    return {
        "propose_write_plan": {
            "type": "function",
            "function": {
                "name": "propose_write_plan",
                "description": (
                    "Before the first write of a request, list every write it needs (tool and fields) in one plan. "
                    "The person confirms the plan once; then perform exactly those writes without asking again. A "
                    "write the plan does not cover is refused with plan_write: call this tool again with just that "
                    "write to amend the plan."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string", "description": "The person's request in one sentence."},
                        "writes": {
                            "type": "array",
                            "description": "Every intended write, in order.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool": {"type": "string", "description": "The write tool, e.g. create_jira_ticket."},
                                    "fields": {"type": "object", "description": "The arguments it will pass."},
                                    "why": {"type": "string"},
                                },
                                "required": ["tool", "fields"],
                            },
                        },
                        "scope": {
                            "type": "array",
                            "description": "Optional: where the plan works (the fields' projects, branches ... count "
                                           "already).",
                            "items": {
                                "type": "object",
                                "properties": {"kind": {"type": "string", "enum": _SCOPE_KINDS},
                                               "value": {"type": "string"}},
                                "required": ["kind", "value"],
                            },
                        },
                    },
                    "required": ["request", "writes"],
                },
            },
        },
    }


__all__ = ["get_write_plan_definitions"]
