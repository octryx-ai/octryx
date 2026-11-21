"""Tool definitions for jira domain."""

from __future__ import annotations

import copy

from .jira_planning import JIRA_PLANNING_DEFINITIONS
from .jira_release import get_jira_release_definitions

_JIRA_TICKET_DEFINITIONS: dict[str, dict] = {
    "search_jira_tickets": {
        "type": "function",
        "function": {
            "name": "search_jira_tickets",
            "description": "Search Jira tickets by free text, issue key or explicit JQL. Do not invent project_key values; omit project_key to search all configured projects or use a key returned by list_jira_projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "jql": {"type": "string"},
                    "project_key": {"type": "string"},
                    "fix_version": {
                        "type": "string",
                        "description": "Filter tickets by one Jira fixVersion/release name.",
                    },
                    "fix_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter tickets by one or more Jira fixVersion/release names.",
                    },
                    "limit": {"type": "integer"},
                    "start_at": {"type": "integer"},
                },
            },
        },
    },
    "get_jira_ticket": {
        "type": "function",
        "function": {
            "name": "get_jira_ticket",
            "description": "Read a Jira ticket for context",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
        },
    },
    "search_jira_users": {
        "type": "function",
        "function": {
            "name": "search_jira_users",
            "description": "Search or list valid Jira users for the configured project, then resolve usernames from names or email fragments",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional name, username or email fragment"},
                    "email": {"type": "string", "description": "Jira Cloud only: the exact email of one Atlassian account"},
                    "account_id": {"type": "string", "description": "Jira Cloud only: the exact Atlassian account id"},
                    "project_key": {"type": "string", "description": "Optional Jira project key"},
                    "limit": {"type": "integer", "description": "Max users to return"},
                },
                "required": [],
            },
        },
    },
    "list_jira_projects": {
        "type": "function",
        "function": {
            "name": "list_jira_projects",
            "description": "List Jira project keys available to this project connector. Use this before project-specific Jira lookups when the user did not name a known project key.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    "list_jira_issue_types": {
        "type": "function",
        "function": {
            "name": "list_jira_issue_types",
            "description": "List the Jira issue types configured for a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Jira project key"},
                },
            },
        },
    },
    "list_jira_priorities": {
        "type": "function",
        "function": {
            "name": "list_jira_priorities",
            "description": "List available Jira priorities for ticket creation and updates",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    "list_jira_transitions": {
        "type": "function",
        "function": {
            "name": "list_jira_transitions",
            "description": "List the available workflow transitions for a Jira ticket",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
        },
    },
    "transition_jira_ticket": {
        "type": "function",
        "function": {
            "name": "transition_jira_ticket",
            "description": "Move a Jira ticket to another workflow transition",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "transition_id": {"type": "string"},
                },
                "required": ["ticket_id", "transition_id"],
            },
        },
    },
    "add_jira_comment": {
        "type": "function",
        "function": {
            "name": "add_jira_comment",
            "description": "Add a comment to a Jira ticket",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["ticket_id", "body"],
            },
        },
    },
    "create_jira_ticket": {
        "type": "function",
        "function": {
            "name": "create_jira_ticket",
            "description": "Create a new Jira issue in a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Jira project key"},
                    "summary": {"type": "string", "description": "Issue title/summary"},
                    "issue_type": {
                        "type": "string",
                        "description": "Issue type, e.g. Story, Bug, Task (default: Task)",
                    },
                    "description": {"type": "string"},
                    "assignee": {"type": "string", "description": "Jira username to assign"},
                    "priority": {"type": "string", "description": "e.g. High, Medium, Low"},
                    "fix_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Release names to set as fixVersion",
                    },
                    "sprint_id": {"type": "integer", "description": "Sprint ID to add the issue to"},
                    "story_points": {"type": "number"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "parent_key": {
                        "type": "string",
                        "description": "Key of the parent issue, e.g. the epic a story belongs to (Jira Cloud)",
                    },
                },
                "required": ["project_key", "summary"],
            },
        },
    },
    "update_jira_ticket": {
        "type": "function",
        "function": {
            "name": "update_jira_ticket",
            "description": "Update fields of a Jira ticket (summary, description, assignee, priority, fix_versions, labels, story_points)",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "assignee": {"type": "string", "description": "Jira username, or empty string to unassign"},
                    "priority": {"type": "string"},
                    "fix_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace fixVersion list with these release names",
                    },
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "story_points": {"type": "number"},
                },
                "required": ["ticket_id"],
            },
        },
    },
}


def get_jira_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for jira tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return {
        **copy.deepcopy({**_JIRA_TICKET_DEFINITIONS, **JIRA_PLANNING_DEFINITIONS}),
        # Live release status: read-only, gated with the Jira connector like every Jira tool.
        **get_jira_release_definitions(),
    }
