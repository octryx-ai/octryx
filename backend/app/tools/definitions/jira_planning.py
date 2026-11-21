"""Tool definitions for Jira versions, release and sprint bundles, boards and sprints."""

from __future__ import annotations

JIRA_PLANNING_DEFINITIONS: dict[str, dict] = {
    "list_jira_versions": {
        "type": "function",
        "function": {
            "name": "list_jira_versions",
            "description": "List Jira versions/releases for the configured Jira project scope. With multiple configured Jira projects, returns versions for all allowed projects; do not guess project keys.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    "create_jira_version": {
        "type": "function",
        "function": {
            "name": "create_jira_version",
            "description": "Create a new version (release) in a Jira project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "name": {"type": "string", "description": "Version/release name"},
                    "description": {"type": "string"},
                    "release_date": {"type": "string", "description": "ISO date, e.g. 2025-06-30"},
                    "start_date": {"type": "string", "description": "ISO date"},
                },
                "required": ["project_key", "name"],
            },
        },
    },
    "release_jira_version": {
        "type": "function",
        "function": {
            "name": "release_jira_version",
            "description": "Mark a Jira version as released",
            "parameters": {
                "type": "object",
                "properties": {
                    "version_id": {"type": "string", "description": "Numeric version ID from list_jira_versions"},
                    "release_date": {"type": "string", "description": "ISO date of release"},
                },
                "required": ["version_id"],
            },
        },
    },
    "create_jira_release_bundle": {
        "type": "function",
        "function": {
            "name": "create_jira_release_bundle",
            "description": "Create or reuse a Jira release, create new tickets for it, update existing tickets to that release, and optionally mark it released",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Jira project key"},
                    "release_name": {"type": "string", "description": "Release/version name, e.g. ai-test-01"},
                    "description": {"type": "string", "description": "Optional release description"},
                    "release_date": {"type": "string", "description": "ISO date, e.g. 2026-04-14"},
                    "release_now": {
                        "type": "boolean",
                        "description": "If true, mark the version as released after ticket processing",
                    },
                    "issue_type": {"type": "string", "description": "Default issue type for new tickets"},
                    "ticket_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Existing Jira tickets to assign to the release",
                    },
                    "tickets": {
                        "type": "array",
                        "description": "New tickets to create for the release",
                        "items": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "description": {"type": "string"},
                                "issue_type": {"type": "string"},
                                "assignee": {"type": "string"},
                                "priority": {"type": "string"},
                                "labels": {"type": "array", "items": {"type": "string"}},
                                "story_points": {"type": "number"},
                            },
                            "required": ["summary"],
                        },
                    },
                },
                "required": ["project_key", "release_name"],
            },
        },
    },
    "create_jira_sprint_bundle": {
        "type": "function",
        "function": {
            "name": "create_jira_sprint_bundle",
            "description": "Create or reuse a Jira release, create or update a sprint, create new tickets, and assign them to the sprint",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string", "description": "Jira project key"},
                    "release_name": {"type": "string", "description": "Release/version name"},
                    "release_description": {"type": "string", "description": "Optional release description"},
                    "release_date": {"type": "string", "description": "ISO date for the release"},
                    "release_now": {
                        "type": "boolean",
                        "description": "If true, mark the version as released after planning",
                    },
                    "sprint_name": {"type": "string", "description": "Sprint name"},
                    "board_id": {"type": "integer", "description": "Optional Jira board ID"},
                    "board_name": {"type": "string", "description": "Optional preferred board name"},
                    "sprint_start_date": {"type": "string", "description": "Sprint start date or datetime"},
                    "sprint_end_date": {"type": "string", "description": "Sprint end date or datetime"},
                    "sprint_goal": {"type": "string", "description": "Sprint goal shown in Jira"},
                    "issue_type": {"type": "string", "description": "Default issue type for new tickets"},
                    "ticket_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Existing Jira tickets to include",
                    },
                    "tickets": {
                        "type": "array",
                        "description": "New tickets to create for the sprint package",
                        "items": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "description": {"type": "string"},
                                "issue_type": {"type": "string"},
                                "assignee": {"type": "string"},
                                "priority": {"type": "string"},
                                "labels": {"type": "array", "items": {"type": "string"}},
                                "story_points": {"type": "number"},
                            },
                            "required": ["summary"],
                        },
                    },
                },
                "required": ["release_name", "sprint_name"],
            },
        },
    },
    "list_jira_boards": {
        "type": "function",
        "function": {
            "name": "list_jira_boards",
            "description": "List Jira boards (Scrum/Kanban) for a project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                },
            },
        },
    },
    "list_jira_sprints": {
        "type": "function",
        "function": {
            "name": "list_jira_sprints",
            "description": "List sprints for a Jira board",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "integer", "description": "Board ID from list_jira_boards"},
                    "state": {
                        "type": "string",
                        "description": "active, future, closed, or comma-separated combination (default: active,future)",
                    },
                },
                "required": ["board_id"],
            },
        },
    },
    "create_jira_sprint": {
        "type": "function",
        "function": {
            "name": "create_jira_sprint",
            "description": "Create or update a Jira sprint on a board",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "integer", "description": "Board ID from list_jira_boards"},
                    "name": {"type": "string", "description": "Sprint name"},
                    "start_date": {"type": "string", "description": "Sprint start date or datetime"},
                    "end_date": {"type": "string", "description": "Sprint end date or datetime"},
                    "goal": {"type": "string", "description": "Sprint goal shown in Jira"},
                },
                "required": ["board_id", "name"],
            },
        },
    },
    "get_sprint_issues": {
        "type": "function",
        "function": {
            "name": "get_sprint_issues",
            "description": "List all issues assigned to a Jira sprint",
            "parameters": {
                "type": "object",
                "properties": {
                    "sprint_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Max results (default 50, max 100)"},
                },
                "required": ["sprint_id"],
            },
        },
    },
    "add_issues_to_sprint": {
        "type": "function",
        "function": {
            "name": "add_issues_to_sprint",
            "description": "Assign one or more Jira issues to a sprint",
            "parameters": {
                "type": "object",
                "properties": {
                    "sprint_id": {"type": "integer"},
                    "ticket_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of issue keys (PROJECT-NUMBER)",
                    },
                },
                "required": ["sprint_id", "ticket_ids"],
            },
        },
    },
}
