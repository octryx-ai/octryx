"""Tool definitions for loki domain."""

from __future__ import annotations


def get_loki_definitions() -> dict[str, dict]:
    return {
        "query_loki": {
            "type": "function",
            "function": {
                "name": "query_loki",
                "description": (
                    "Search logs via Loki with LogQL over a time window. On an alert run the window defaults to "
                    "the alert's and every stream selector must name the alert target's labels."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "LogQL"},
                        "limit": {"type": "integer", "description": "Max lines, at most 1000 (default 100)"},
                        "start": {
                            "type": "string",
                            "description": "RFC3339 start (default: the alert window, else 1h ago)",
                        },
                        "end": {"type": "string", "description": "RFC3339 end (default: now, within the alert window)"},
                        "since": {
                            "type": "string",
                            "description": "Relative start before end, e.g. 30m, 6h (max 24h span)",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    }
