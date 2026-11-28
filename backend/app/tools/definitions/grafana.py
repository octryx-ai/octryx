"""Tool definitions for grafana domain."""

from __future__ import annotations


def get_grafana_definitions() -> dict[str, dict]:
    return {
        "read_grafana_alert": {
            "type": "function",
            "function": {
                "name": "read_grafana_alert",
                "description": "Read details of a specific Grafana alert by ID",
                "parameters": {
                    "type": "object",
                    "properties": {"alert_id": {"type": "string"}},
                    "required": ["alert_id"],
                },
            },
        },
        "list_grafana_alerts": {
            "type": "function",
            "function": {
                "name": "list_grafana_alerts",
                "description": "List all active Grafana alerts",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "render_panel_as_image": {
            "type": "function",
            "function": {
                "name": "render_panel_as_image",
                "description": "Render a Grafana panel as an image",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_uid": {"type": "string"},
                        "panel_id": {"type": "integer"},
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "theme": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["dashboard_uid", "panel_id"],
                },
            },
        },
        "create_snapshot": {
            "type": "function",
            "function": {
                "name": "create_snapshot",
                "description": "Create a Grafana snapshot for a dashboard",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_uid": {"type": "string"},
                        "dashboard": {"type": "object"},
                        "name": {"type": "string"},
                        "expires": {"type": "integer"},
                    },
                },
            },
        },
    }
