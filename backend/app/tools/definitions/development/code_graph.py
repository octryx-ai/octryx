"""Tool definitions for code-graph navigation and impact analysis."""

from __future__ import annotations

# ruff: noqa: E501

CODE_GRAPH_DEFINITIONS: dict[str, dict] = {
    "code_node": {
        "type": "function",
        "function": {
            "name": "code_node",
            "description": "Look up a native code graph node by id, symbol name, path or text query",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                    "include_source": {"type": "boolean"},
                },
            },
        },
    },
    "code_neighbors": {
        "type": "function",
        "function": {
            "name": "code_neighbors",
            "description": "Traverse bounded native code graph neighbors for a node, symbol name, path or query",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "depth": {"type": "integer"},
                    "max_nodes": {"type": "integer"},
                },
            },
        },
    },
    "code_trace": {
        "type": "function",
        "function": {
            "name": "code_trace",
            "description": "Find a bounded shortest path between two native code graph nodes or symbols",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "source": {"type": "string"},
                    "from": {"type": "string"},
                    "target": {"type": "string"},
                    "to": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "max_depth": {"type": "integer"},
                    "include_source": {"type": "boolean"},
                },
            },
        },
    },
    "code_graph_stats": {
        "type": "function",
        "function": {
            "name": "code_graph_stats",
            "description": "Return native code graph counts, distributions and top-degree nodes",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "code_graph_status": {
        "type": "function",
        "function": {
            "name": "code_graph_status",
            "description": "Return native code graph readiness, freshness, latest run and row-count metadata",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                },
            },
        },
    },
    "code_god_nodes": {
        "type": "function",
        "function": {
            "name": "code_god_nodes",
            "description": "Rank high-degree native code graph nodes that may need review focus",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "relation": {"type": "string"},
                    "node_type": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "code_affected": {
        "type": "function",
        "function": {
            "name": "code_affected",
            "description": "Traverse dependents or dependencies that may be affected by a code graph node",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "depth": {"type": "integer"},
                    "max_nodes": {"type": "integer"},
                },
            },
        },
    },
    "code_impact": {
        "type": "function",
        "function": {
            "name": "code_impact",
            "description": "Traverse graph-native dependents that may be impacted by a code graph node",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "depth": {"type": "integer"},
                    "max_nodes": {"type": "integer"},
                },
            },
        },
    },
    "code_callees": {
        "type": "function",
        "function": {
            "name": "code_callees",
            "description": "Return direct static callees for a native code graph node, symbol, path or query",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "code_files": {
        "type": "function",
        "function": {
            "name": "code_files",
            "description": "List files from the latest native code graph run with optional path and language filters",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "language": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "code_context": {
        "type": "function",
        "function": {
            "name": "code_context",
            "description": "Return a budgeted native code graph context bundle around a node, symbol, path or query",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "depth": {"type": "integer"},
                    "max_nodes": {"type": "integer"},
                    "budget_chars": {"type": "integer"},
                },
            },
        },
    },
    "code_explore": {
        "type": "function",
        "function": {
            "name": "code_explore",
            "description": "Return a compact native code graph exploration bundle before broad repository scanning",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "node_id": {"type": "string"},
                    "id": {"type": "string"},
                    "query": {"type": "string"},
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "relation": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                    "depth": {"type": "integer"},
                    "max_nodes": {"type": "integer"},
                    "budget_chars": {"type": "integer"},
                },
            },
        },
    },
    "code_impact_analysis": {
        "type": "function",
        "function": {
            "name": "code_impact_analysis",
            "description": "Estimate impacted files, related symbols and review scope for a repository symbol",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["symbol"],
            },
        },
    },
}
