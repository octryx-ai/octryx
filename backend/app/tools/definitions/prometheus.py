"""Tool definitions for prometheus domain."""

from __future__ import annotations


def get_prometheus_definitions() -> dict[str, dict]:
    return {
        "query_prometheus": {
            "type": "function",
            "function": {
                "name": "query_prometheus",
                "description": (
                    "Execute a PromQL query against Prometheus (instant + range). On an alert run the range is "
                    "the alert window and every selector must name the alert target's labels."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "start": {"type": "string", "description": "RFC3339 range start (default: the alert window)"},
                        "end": {"type": "string", "description": "RFC3339 range end (default: now)"},
                        "duration": {
                            "type": "string",
                            "description": "Without start/end and outside an alert: e.g. 1h, 30m, 1d",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    }
