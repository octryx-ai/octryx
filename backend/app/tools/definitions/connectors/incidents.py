"""Tool definitions for incident management (create, update, resolve, escalate)."""

from __future__ import annotations

INCIDENT_DEFINITIONS: dict[str, dict] = {
    "create_incident": {
        "type": "function",
        "function": {
            "name": "create_incident",
            "description": "Create an incident in PagerDuty, an alert in OpsGenie, or an incident in Statuspage",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Optional explicit provider override: pagerduty, opsgenie or statuspage",
                    },
                    "title": {"type": "string"},
                    "message": {"type": "string", "description": "Alias for title"},
                    "details": {"type": "string"},
                    "description": {"type": "string", "description": "Alias for details"},
                    "page_id": {"type": "string", "description": "Statuspage page id"},
                    "status": {"type": "string", "description": "Statuspage incident status such as investigating"},
                    "component_ids": {"type": "array", "items": {"type": "string"}},
                    "component_status": {
                        "type": "string",
                        "description": "Optional Statuspage component status override",
                    },
                    "impact_override": {"type": "string", "description": "Optional Statuspage impact override"},
                    "service_id": {"type": "string", "description": "PagerDuty service id"},
                    "escalation_policy_id": {"type": "string"},
                    "assignee_ids": {"type": "array", "items": {"type": "string"}},
                    "responder_ids": {"type": "array", "items": {"type": "string"}},
                    "team_id": {"type": "string", "description": "OpsGenie team id"},
                    "priority": {"type": "string", "description": "OpsGenie priority such as P1-P5"},
                    "urgency": {"type": "string", "description": "PagerDuty urgency such as high or low"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "metadata": {"type": "object"},
                },
            },
        },
    },
    "update_incident": {
        "type": "function",
        "function": {
            "name": "update_incident",
            "description": "Update an Atlassian Statuspage incident",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "title": {"type": "string"},
                    "name": {"type": "string", "description": "Alias for title"},
                    "status": {"type": "string"},
                    "body": {"type": "string"},
                    "details": {"type": "string", "description": "Alias for body"},
                    "message": {"type": "string", "description": "Alias for body"},
                    "component_ids": {"type": "array", "items": {"type": "string"}},
                    "component_status": {"type": "string"},
                },
                "required": ["incident_id"],
            },
        },
    },
    "resolve_incident": {
        "type": "function",
        "function": {
            "name": "resolve_incident",
            "description": "Resolve an Atlassian Statuspage incident",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "incident_id": {"type": "string"},
                },
                "required": ["incident_id"],
            },
        },
    },
    "escalate": {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Escalate an existing PagerDuty incident or OpsGenie alert",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "alert_id": {"type": "string", "description": "Alias for incident_id"},
                    "message": {"type": "string"},
                    "responder_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required for PagerDuty escalation",
                    },
                    "identifier_type": {"type": "string", "description": "OpsGenie identifier type (default: id)"},
                    "from_email": {"type": "string"},
                },
            },
        },
    },
    "get_escalation_policy": {
        "type": "function",
        "function": {
            "name": "get_escalation_policy",
            "description": "Get escalation policy metadata from PagerDuty or OpsGenie",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "escalation_policy_id": {"type": "string"},
                    "escalation_id": {"type": "string", "description": "Alias for opsgenie escalation id"},
                    "identifier_type": {"type": "string"},
                },
            },
        },
    },
}
