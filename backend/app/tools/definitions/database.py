"""Tool definitions for database domain."""

from __future__ import annotations


def get_database_definitions() -> dict[str, dict]:
    return {
        "list_gcp_cloud_sql_instances": {
            "type": "function",
            "function": {
                "name": "list_gcp_cloud_sql_instances",
                "description": "List Cloud SQL instances",
                "parameters": {
                    "type": "object",
                    "properties": {"project_id": {"type": "string"}, "limit": {"type": "integer"}},
                },
            },
        },
        "get_gcp_cloud_sql_metrics": {
            "type": "function",
            "function": {
                "name": "get_gcp_cloud_sql_metrics",
                "description": "Get Cloud Monitoring metrics for Cloud SQL",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "database_id": {"type": "string"},
                        "instance_id": {"type": "string"},
                        "metric_type": {"type": "string"},
                        "hours": {"type": "integer"},
                    },
                    "required": ["database_id"],
                },
            },
        },
    }
