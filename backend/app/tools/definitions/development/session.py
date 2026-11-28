"""Tool definitions for web access, session todos and evidence, and workflow selection."""

from __future__ import annotations

# ruff: noqa: E501

SESSION_DEFINITIONS: dict[str, dict] = {
    "web_fetch": {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its content as markdown (default), plain text, or raw HTML. Max 2MB. The result carries source_url and a cite_as markdown link; cite what you use from the page by copying cite_as.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "format": {"type": "string", "enum": ["markdown", "text", "html"]},
                    "timeout": {"type": "integer"},
                },
                "required": ["url"],
            },
        },
    },
    "html_to_markdown": {
        "type": "function",
        "function": {
            "name": "html_to_markdown",
            "description": "Convert raw HTML into readable markdown before storing or reusing page content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "Raw HTML content to convert"},
                },
                "required": ["html"],
            },
        },
    },
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web through the governed search provider (platform blocklist, the Workspace's trusted sources). Returns titles, URLs and snippets; cite each fact you use by copying its result's cite_as.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer"},
                    "include_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional domain allowlist for the search, e.g. ['spring.io', 'docs.spring.io']",
                    },
                    "exclude_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional domain blocklist for the search.",
                    },
                    "exclude_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional title/snippet terms to exclude from results.",
                    },
                    "exclude_preprints": {
                        "type": "boolean",
                        "description": "Exclude preprints, preview papers, and similar draft-only publications.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "todo_read": {
        "type": "function",
        "function": {
            "name": "todo_read",
            "description": "Read the current todo list for this agent session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "todo_write": {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Update the session todo list. Each todo needs: id, subject, status (pending|in_progress|completed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "subject": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                "description": {"type": "string"},
                            },
                            "required": ["id", "subject", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    "freeze_context": {
        "type": "function",
        "function": {
            "name": "freeze_context",
            "description": "Freeze the current session context under a named checkpoint. After freezing, no further tool calls are allowed until `release_context` is called.",
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_name": {"type": "string", "description": "Human-readable checkpoint name"},
                },
                "required": ["checkpoint_name"],
            },
        },
    },
    "get_session_summary_evidence": {
        "type": "function",
        "function": {
            "name": "get_session_summary_evidence",
            "description": (
                "Load the full stored session message behind a session summary evidence reference "
                "such as [msg:<id>] or [tool_call:<id>]. Read-only and limited to the current session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference_id": {
                        "type": "string",
                        "description": "Reference id from the session summary, e.g. 'msg:<message_id>' or 'tool_call:<tool_call_id>'.",
                    },
                    "detail_level": {"type": "string", "enum": ["excerpt", "full"]},
                },
                "required": ["reference_id"],
            },
        },
    },
    "load_tool_artifact": {
        "type": "function",
        "function": {
            "name": "load_tool_artifact",
            "description": (
                "Load more detail for a prior tool result by artifact_id. "
                "Use this only when an older tool snapshot in context is too compact. "
                "Optional `path` can target a nested field like `items.0`. "
                "Read-only and limited to the current session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "description": "Artifact id from a prior tool result envelope.",
                    },
                    "detail_level": {"type": "string", "enum": ["excerpt", "full"]},
                    "path": {
                        "type": "string",
                        "description": "Optional dotted path into the stored payload, e.g. 'items.0'.",
                    },
                    "max_chars": {"type": "integer"},
                    "max_items": {"type": "integer"},
                },
                "required": ["artifact_id"],
            },
        },
    },
    "list_available_workflows": {
        "type": "function",
        "function": {
            "name": "list_available_workflows",
            "description": (
                "List the task workflows this project can enter via `start_workflow`. "
                "Each entry reports workflow_id, description, intent_type, phases with preferred "
                "tools, and whether the project can execute it (with the blocking reason when not)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "select_workflow": {
        "type": "function",
        "function": {
            "name": "select_workflow",
            "description": (
                "Choose a workflow of the system prompt's Workflow catalog when the request clearly matches an "
                "entry. A workflow never runs inside this turn: the answer says how the user starts it as a "
                "workflow run for a Work item. Not when nothing matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_key": {
                        "type": "string",
                        "description": "workflow_key of a catalog entry.",
                    },
                },
                "required": ["workflow_key"],
            },
        },
    },
    "start_workflow": {
        "type": "function",
        "function": {
            "name": "start_workflow",
            "description": (
                "Propose a workflow from `list_available_workflows` for the user's request, with a short "
                "`reason` stating why it fits. It never starts anything: the user confirms and starts it as a "
                "workflow run for a Work item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "workflow_key from `list_available_workflows`.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short statement why this workflow fits the current user request.",
                    },
                },
                "required": ["workflow_id", "reason"],
            },
        },
    },
}
