"""Tool definitions for admin domain."""

from __future__ import annotations

import copy

from .admin_operations import ADMIN_OPERATION_DEFINITIONS

_ADMIN_ACCESS_DEFINITIONS: dict[str, dict] = {
    "admin_list_users": {
        "type": "function",
        "function": {
            "name": "admin_list_users",
            "description": "List all users with their roles and status. Admin only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_create_user": {
        "type": "function",
        "function": {
            "name": "admin_create_user",
            "description": "Create a new user account with roles. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "email": {"type": "string"},
                    "password": {"type": "string"},
                    "display_name": {"type": "string"},
                    "roles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "e.g. ['viewer'] or ['operator']",
                    },
                },
                "required": ["username", "email", "password"],
            },
        },
    },
    "admin_update_user": {
        "type": "function",
        "function": {
            "name": "admin_update_user",
            "description": "Update an existing user: email, display_name, password, is_active, or roles. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "user_id": {"type": "string"},
                    "email": {"type": "string"},
                    "display_name": {"type": "string"},
                    "password": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    "admin_delete_user": {
        "type": "function",
        "function": {
            "name": "admin_delete_user",
            "description": "Deactivate or permanently delete a user. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "user_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["deactivate", "delete"],
                        "description": "deactivate (default, reversible) or delete (permanent)",
                    },
                },
            },
        },
    },
    "admin_list_roles": {
        "type": "function",
        "function": {
            "name": "admin_list_roles",
            "description": "List all roles with permissions and user counts. Admin only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "admin_create_role": {
        "type": "function",
        "function": {
            "name": "admin_create_role",
            "description": "Create a custom role with permissions. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "permissions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "resource": {"type": "string"},
                                "action": {"type": "string", "enum": ["read", "write", "delete"]},
                            },
                        },
                    },
                },
                "required": ["name"],
            },
        },
    },
    "admin_assign_role": {
        "type": "function",
        "function": {
            "name": "admin_assign_role",
            "description": "Assign or remove a role from a user. Admin only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "role": {"type": "string"},
                    "action": {"type": "string", "enum": ["assign", "remove"]},
                },
                "required": ["username", "role"],
            },
        },
    },
}


def get_admin_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for admin tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**_ADMIN_ACCESS_DEFINITIONS, **ADMIN_OPERATION_DEFINITIONS})
