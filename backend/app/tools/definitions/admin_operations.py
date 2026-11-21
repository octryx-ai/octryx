"""Tool definitions for admin agent, task, channel, audit, usage, session and settings tools."""

from __future__ import annotations

ADMIN_OPERATION_DEFINITIONS: dict[str, dict] = {
    "admin_list_agents": {
        "type": "function",
        "function": {
            "name": "admin_list_agents",
            "description": "List all agent definitions. Admin/operator only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_get_agent": {
        "type": "function",
        "function": {
            "name": "admin_get_agent",
            "description": "Get full details of an agent definition including steps. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "agent_id": {"type": "string"},
                },
            },
        },
    },
    "admin_list_tasks": {
        "type": "function",
        "function": {
            "name": "admin_list_tasks",
            "description": "List all scheduled tasks (cron jobs). Admin/operator only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_list_channels": {
        "type": "function",
        "function": {
            "name": "admin_list_channels",
            "description": "List configured channel instances. Admin/operator only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_create_channel": {
        "type": "function",
        "function": {
            "name": "admin_create_channel",
            "description": "Create a new channel instance such as Slack, Teams or Email. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin_id": {"type": "string"},
                    "name": {"type": "string"},
                    "project_id": {"type": "string"},
                    "project_name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "config": {"type": "object"},
                },
                "required": ["plugin_id", "name", "config"],
            },
        },
    },
    "admin_update_channel": {
        "type": "function",
        "function": {
            "name": "admin_update_channel",
            "description": "Update a configured channel instance. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "channel_name": {"type": "string"},
                    "name": {"type": "string"},
                    "project_id": {"type": "string"},
                    "project_name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "config": {"type": "object"},
                    "merge_config": {"type": "object"},
                },
            },
        },
    },
    "admin_update_task": {
        "type": "function",
        "function": {
            "name": "admin_update_task",
            "description": "Update a task configuration, including output channel routing. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "task_name": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "config": {"type": "object"},
                    "merge_config": {"type": "object"},
                    "output_channel_id": {"type": "string"},
                    "output_channel_name": {"type": "string"},
                    "output_target": {"type": "string"},
                    "clear_output_channel": {"type": "boolean"},
                },
            },
        },
    },
    "admin_create_agent": {
        "type": "function",
        "function": {
            "name": "admin_create_agent",
            "description": "Create a new DB-backed agent definition with optional steps or by cloning an existing agent. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "goal": {"type": "string"},
                    "runtime_target_id": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "thinking_level": {"type": "string"},
                    "system_prompt": {"type": "string"},
                    "output_prompt": {"type": "string"},
                    "branch_prefix": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "clone_from_agent_id": {"type": "string"},
                    "clone_from_name": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "position": {"type": "integer"},
                                "name": {"type": "string"},
                                "step_type": {"type": "string"},
                                "instructions": {"type": "string"},
                                "success_criteria": {"type": "string"},
                                "allowed_tools": {"type": "array", "items": {"type": "string"}},
                                "is_enabled": {"type": "boolean"},
                            },
                        },
                    },
                },
                "required": ["name"],
            },
        },
    },
    "admin_update_agent": {
        "type": "function",
        "function": {
            "name": "admin_update_agent",
            "description": "Update an existing DB-backed agent definition. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "goal": {"type": "string"},
                    "runtime_target_id": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "thinking_level": {"type": "string"},
                    "system_prompt": {"type": "string"},
                    "output_prompt": {"type": "string"},
                    "branch_prefix": {"type": "string"},
                    "is_active": {"type": "boolean"},
                },
            },
        },
    },
    "admin_get_thread_diagnostics": {
        "type": "function",
        "function": {
            "name": "admin_get_thread_diagnostics",
            "description": "Inspect a thread/session and summarize likely causes for bad behavior. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                },
            },
        },
    },
    "admin_view_audit_log": {
        "type": "function",
        "function": {
            "name": "admin_view_audit_log",
            "description": "View recent audit log entries. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "action": {"type": "string"},
                    "resource_type": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "admin_get_usage_stats": {
        "type": "function",
        "function": {
            "name": "admin_get_usage_stats",
            "description": "Get token usage and cost statistics by model. Admin/operator only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look-back period in days (default 7)"},
                    "user_id": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
        },
    },
    "admin_list_sessions": {
        "type": "function",
        "function": {
            "name": "admin_list_sessions",
            "description": "List chat sessions across all users. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["running", "active", "archived"]},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "admin_list_webhooks": {
        "type": "function",
        "function": {
            "name": "admin_list_webhooks",
            "description": "List all configured webhooks. Admin/operator only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_platform_status": {
        "type": "function",
        "function": {
            "name": "admin_platform_status",
            "description": "Get platform status overview: users, active sessions, tasks, MCP servers. Admin/operator only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
}
