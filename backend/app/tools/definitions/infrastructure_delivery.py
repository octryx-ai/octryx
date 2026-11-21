"""Tool definitions for Helm releases, container registries and Terraform."""

from __future__ import annotations

# ruff: noqa: E501

INFRASTRUCTURE_DELIVERY_DEFINITIONS: dict[str, dict] = {
    "list_releases": {
        "type": "function",
        "function": {
            "name": "list_releases",
            "description": "List Helm releases in an allowed namespace",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_status": {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": "Get status details for a Helm release",
            "parameters": {
                "type": "object",
                "properties": {
                    "release_name": {"type": "string"},
                    "name": {"type": "string", "description": "Alias for release_name"},
                    "namespace": {"type": "string"},
                },
            },
        },
    },
    "get_history": {
        "type": "function",
        "function": {
            "name": "get_history",
            "description": "Get revision history for a Helm release",
            "parameters": {
                "type": "object",
                "properties": {
                    "release_name": {"type": "string"},
                    "name": {"type": "string", "description": "Alias for release_name"},
                    "namespace": {"type": "string"},
                },
            },
        },
    },
    "upgrade": {
        "type": "function",
        "function": {
            "name": "upgrade",
            "description": "Run helm upgrade --install with dry-run support and approval gating for real changes",
            "parameters": {
                "type": "object",
                "properties": {
                    "release_name": {"type": "string"},
                    "name": {"type": "string", "description": "Alias for release_name"},
                    "chart": {"type": "string"},
                    "namespace": {"type": "string"},
                    "values_file": {"type": "string"},
                    "set_values": {"type": "array", "items": {"type": "string"}},
                    "dry_run": {"type": "boolean"},
                    "wait": {"type": "boolean"},
                    "timeout": {"type": "string"},
                },
            },
        },
    },
    "rollback": {
        "type": "function",
        "function": {
            "name": "rollback",
            "description": "Rollback a Helm release revision with approval gating",
            "parameters": {
                "type": "object",
                "properties": {
                    "release_name": {"type": "string"},
                    "name": {"type": "string", "description": "Alias for release_name"},
                    "namespace": {"type": "string"},
                    "revision": {"type": "string"},
                    "wait": {"type": "boolean"},
                },
                "required": ["revision"],
            },
        },
    },
    "list_repositories": {
        "type": "function",
        "function": {
            "name": "list_repositories",
            "description": "List repositories from a Docker Registry or Harbor",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Optional override: registry or harbor"},
                    "project": {"type": "string", "description": "Harbor project name"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_tags": {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List tags for an allowed Docker Registry or Harbor repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "repo": {"type": "string", "description": "Alias for repository"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_image_vulnerabilities": {
        "type": "function",
        "function": {
            "name": "get_image_vulnerabilities",
            "description": "Get image vulnerability information from Harbor",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "repository": {"type": "string"},
                    "repo": {"type": "string", "description": "Alias for repository"},
                    "reference": {"type": "string"},
                    "tag": {"type": "string", "description": "Alias for reference"},
                    "digest": {"type": "string", "description": "Alias for reference"},
                },
            },
        },
    },
    "delete_tag": {
        "type": "function",
        "function": {
            "name": "delete_tag",
            "description": "Delete a tag from an allowed Docker Registry or Harbor repository with approval",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "repo": {"type": "string", "description": "Alias for repository"},
                    "tag": {"type": "string"},
                },
                "required": ["tag"],
            },
        },
    },
    "plan": {
        "type": "function",
        "function": {
            "name": "plan",
            "description": "Run terraform or opentofu plan and return a reusable plan file plus change summary",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "plan_file": {"type": "string"},
                    "var_file": {"type": "string"},
                    "destroy": {"type": "boolean"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "apply": {
        "type": "function",
        "function": {
            "name": "apply",
            "description": "Run terraform or opentofu apply behind an approval gate",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "plan_file": {"type": "string"},
                    "var_file": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "show_state": {
        "type": "function",
        "function": {
            "name": "show_state",
            "description": "Show current terraform or opentofu state",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "list_resources": {
        "type": "function",
        "function": {
            "name": "list_resources",
            "description": "List resources from terraform or opentofu state",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "get_output": {
        "type": "function",
        "function": {
            "name": "get_output",
            "description": "Read terraform or opentofu outputs",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "name": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
}
