"""Tool definitions for the external SaaS integration domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


INTEGRATIONS_DEFINITIONS: dict[str, dict] = {
    "list_issues": {
        "type": "function",
        "function": {
            "name": "list_issues",
            "description": "List SonarQube or Linear issues",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "sonarqube or linear"},
                    "project_key": {"type": "string"},
                    "team_id": {"type": "string"},
                    "query": {"type": "string"},
                    "state_id": {"type": "string"},
                    "severities": {"type": "array", "items": {"type": "string"}},
                    "types": {"type": "array", "items": {"type": "string"}},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "create_issue": {
        "type": "function",
        "function": {
            "name": "create_issue",
            "description": "Create a Linear issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "number"},
                    "state_id": {"type": "string"},
                    "label_ids": {"type": "array", "items": {"type": "string"}},
                    "assignee_id": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    "update_issue": {
        "type": "function",
        "function": {
            "name": "update_issue",
            "description": "Update a Linear issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "number"},
                    "state_id": {"type": "string"},
                    "label_ids": {"type": "array", "items": {"type": "string"}},
                    "assignee_id": {"type": "string"},
                },
                "required": ["issue_id"],
            },
        },
    },
    "search_notion_pages": {
        "type": "function",
        "function": {
            "name": "search_notion_pages",
            "description": "Search pages and databases in Notion",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filter": {"type": "string", "description": "page or database"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "get_notion_page": {
        "type": "function",
        "function": {
            "name": "get_notion_page",
            "description": "Fetch a Notion page and its first child blocks",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max number of child blocks"},
                },
                "required": ["page_id"],
            },
        },
    },
    "search_sharepoint": {
        "type": "function",
        "function": {
            "name": "search_sharepoint",
            "description": "Search SharePoint sites via Microsoft Graph",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "list_sharepoint_site_pages": {
        "type": "function",
        "function": {
            "name": "list_sharepoint_site_pages",
            "description": "List pages for an allowed SharePoint site path",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_path": {"type": "string", "description": "SharePoint site path like /sites/sample-app"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_servicenow_records": {
        "type": "function",
        "function": {
            "name": "list_servicenow_records",
            "description": "List records from an allowed ServiceNow table",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "query": {"type": "string", "description": "ServiceNow sysparm_query filter"},
                    "fields": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "limit": {"type": "integer"},
                    "display_value": {"type": "string"},
                },
                "required": ["table"],
            },
        },
    },
    "get_servicenow_record": {
        "type": "function",
        "function": {
            "name": "get_servicenow_record",
            "description": "Read a ServiceNow record by sys_id from an allowed table",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "sys_id": {"type": "string"},
                    "fields": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "display_value": {"type": "string"},
                },
                "required": ["table", "sys_id"],
            },
        },
    },
    "list_servicenow_changes": {
        "type": "function",
        "function": {
            "name": "list_servicenow_changes",
            "description": "List ServiceNow change requests",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "ServiceNow sysparm_query filter"},
                    "fields": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "limit": {"type": "integer"},
                },
            },
        },
    },
}


def get_integrations_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for integrations tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(INTEGRATIONS_DEFINITIONS)
