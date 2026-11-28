"""Tool definitions for the observability and code-quality scanning domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


_OBSERVABILITY_DEFINITIONS: dict[str, dict] = {
    "get_dashboard_json": {
        "type": "function",
        "function": {
            "name": "get_dashboard_json",
            "description": "Get the full Grafana dashboard JSON by UID",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_uid": {"type": "string"},
                },
                "required": ["dashboard_uid"],
            },
        },
    },
    "get_project_metrics": {
        "type": "function",
        "function": {
            "name": "get_project_metrics",
            "description": "Get SonarQube project metrics for an allowed project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["project_key"],
            },
        },
    },
    "get_quality_gate": {
        "type": "function",
        "function": {
            "name": "get_quality_gate",
            "description": "Get the SonarQube quality gate status for an allowed project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_key": {"type": "string"},
                },
                "required": ["project_key"],
            },
        },
    },
    "list_vulnerabilities": {
        "type": "function",
        "function": {
            "name": "list_vulnerabilities",
            "description": "List Snyk vulnerabilities for an allowed project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["project_id"],
            },
        },
    },
    "get_severity": {
        "type": "function",
        "function": {
            "name": "get_severity",
            "description": "Get severity details for a Snyk issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "issue_id": {"type": "string"},
                },
                "required": ["project_id", "issue_id"],
            },
        },
    },
    "get_fix_advice": {
        "type": "function",
        "function": {
            "name": "get_fix_advice",
            "description": "Get fix advice for a Snyk issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "issue_id": {"type": "string"},
                },
                "required": ["project_id", "issue_id"],
            },
        },
    },
    "query_metrics": {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "Query Datadog metrics for a time range",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "from": {"type": "integer"},
                    "to": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "list_monitors": {
        "type": "function",
        "function": {
            "name": "list_monitors",
            "description": "List Datadog monitors",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_events": {
        "type": "function",
        "function": {
            "name": "get_events",
            "description": "Get Datadog events for a time range",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "priority": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_apm_traces": {
        "type": "function",
        "function": {
            "name": "get_apm_traces",
            "description": "Search Datadog APM traces",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "service": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_service_map": {
        "type": "function",
        "function": {
            "name": "get_service_map",
            "description": "Get Datadog service dependencies",
            "parameters": {
                "type": "object",
                "properties": {
                    "env": {"type": "string"},
                },
            },
        },
    },
    "nrql_query": {
        "type": "function",
        "function": {
            "name": "nrql_query",
            "description": "Run a New Relic NRQL query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "account_id": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "get_alerts": {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "Get alerts from New Relic or Splunk",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Optional override: newrelic or splunk"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_apm_data": {
        "type": "function",
        "function": {
            "name": "get_apm_data",
            "description": "Get New Relic APM application data",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "service_name": {"type": "string"},
                },
            },
        },
    },
    "get_elasticsearch_cluster_health": {
        "type": "function",
        "function": {
            "name": "get_elasticsearch_cluster_health",
            "description": "Read Elasticsearch cluster health",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "search_elasticsearch_documents": {
        "type": "function",
        "function": {
            "name": "search_elasticsearch_documents",
            "description": "Search documents in an allowed Elasticsearch index",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "string"},
                    "query": {"type": "string", "description": "Lucene/query_string query"},
                    "query_body": {"type": "object", "description": "Full Elasticsearch query DSL body"},
                    "limit": {"type": "integer"},
                },
                "required": ["index"],
            },
        },
    },
    "search_logs": {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": "Run a Splunk SPL search and return structured results",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "search": {"type": "string", "description": "Alias for query"},
                    "earliest_time": {"type": "string"},
                    "latest_time": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_saved_searches": {
        "type": "function",
        "function": {
            "name": "get_saved_searches",
            "description": "List Splunk saved searches",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_index_stats": {
        "type": "function",
        "function": {
            "name": "get_index_stats",
            "description": "Return index-level event counts from Splunk",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
}


def get_observability_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(_OBSERVABILITY_DEFINITIONS)
