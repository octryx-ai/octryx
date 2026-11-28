"""Tool definitions for the incident-management and delivery-status domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


INCIDENT_MANAGEMENT_DEFINITIONS: dict[str, dict] = {
    "list_components": {
        "type": "function",
        "function": {
            "name": "list_components",
            "description": "List Atlassian Statuspage components for the configured page",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "update_component_status": {
        "type": "function",
        "function": {
            "name": "update_component_status",
            "description": "Update the status of an Atlassian Statuspage component",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "component_id": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["component_id", "status"],
            },
        },
    },
    "list_oncall": {
        "type": "function",
        "function": {
            "name": "list_oncall",
            "description": "List current on-call responders from PagerDuty or OpsGenie",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "schedule_id": {"type": "string"},
                    "escalation_policy_id": {"type": "string"},
                    "team_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "resolve": {
        "type": "function",
        "function": {
            "name": "resolve",
            "description": "Resolve a PagerDuty incident or OpsGenie alert",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "alert_id": {"type": "string", "description": "Alias for incident_id"},
                    "message": {"type": "string"},
                    "identifier_type": {"type": "string"},
                    "from_email": {"type": "string"},
                },
            },
        },
    },
    "get_schedule": {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": "Get schedule metadata from PagerDuty or OpsGenie",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "schedule_id": {"type": "string"},
                    "identifier_type": {"type": "string"},
                },
                "required": ["schedule_id"],
            },
        },
    },
    "list_apps": {
        "type": "function",
        "function": {
            "name": "list_apps",
            "description": "List ArgoCD applications visible to the configured connector",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_app_status": {
        "type": "function",
        "function": {
            "name": "get_app_status",
            "description": "Get sync and health status of a single ArgoCD application",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "application": {"type": "string", "description": "Alias for app_name"},
                },
            },
        },
    },
    "sync_app": {
        "type": "function",
        "function": {
            "name": "sync_app",
            "description": "Trigger a sync of a single ArgoCD application",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "application": {"type": "string"},
                    "revision": {"type": "string"},
                    "prune": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                },
            },
        },
    },
    "get_rollout_status": {
        "type": "function",
        "function": {
            "name": "get_rollout_status",
            "description": "Inspect rollout and operation state of a single ArgoCD application",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "application": {"type": "string"},
                },
            },
        },
    },
    "rollback_app": {
        "type": "function",
        "function": {
            "name": "rollback_app",
            "description": "Rollback an ArgoCD application to a previous history id",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "application": {"type": "string"},
                    "history_id": {"type": "integer"},
                    "prune": {"type": "boolean"},
                },
            },
        },
    },
    "list_events": {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List recent events of a single ArgoCD application",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "application": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
}


def get_incident_management_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(INCIDENT_MANAGEMENT_DEFINITIONS)
