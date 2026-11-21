"""Tool definitions for syntax checks, workspace snapshots and LSP queries."""

from __future__ import annotations

# ruff: noqa: E501

SNAPSHOT_LSP_DEFINITIONS: dict[str, dict] = {
    "check_file_syntax": {
        "type": "function",
        "function": {
            "name": "check_file_syntax",
            "description": "Check syntax of a file (.py, .sh, .json, .yaml, .go, .java, .ts, .js). Returns valid=true/false and errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "language": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    "snapshot_create": {
        "type": "function",
        "function": {
            "name": "snapshot_create",
            "description": "Save current workspace state as a snapshot. Returns SHA for restore/diff. Call before risky changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                },
            },
        },
    },
    "snapshot_restore": {
        "type": "function",
        "function": {
            "name": "snapshot_restore",
            "description": "Restore workspace to a snapshot by SHA. WARNING: Overwrites all current changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sha": {"type": "string"},
                },
                "required": ["sha"],
            },
        },
    },
    "snapshot_diff": {
        "type": "function",
        "function": {
            "name": "snapshot_diff",
            "description": "Show unified diff between a snapshot and current workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sha": {"type": "string"},
                },
                "required": ["sha"],
            },
        },
    },
    "snapshot_list": {
        "type": "function",
        "function": {
            "name": "snapshot_list",
            "description": "List all snapshots saved in this agent session (SHA, label, timestamp).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "snapshot_diff_structured": {
        "type": "function",
        "function": {
            "name": "snapshot_diff_structured",
            "description": "Return per-file structured diff between a snapshot and current workspace. Each entry includes status, before/after content, additions/deletions.",
            "parameters": {
                "type": "object",
                "properties": {"sha": {"type": "string"}},
                "required": ["sha"],
            },
        },
    },
    "snapshot_diff_range": {
        "type": "function",
        "function": {
            "name": "snapshot_diff_range",
            "description": "Return per-file structured diff between two snapshot SHAs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sha_from": {"type": "string"},
                    "sha_to": {"type": "string"},
                },
                "required": ["sha_from", "sha_to"],
            },
        },
    },
    "codesearch": {
        "type": "function",
        "function": {
            "name": "codesearch",
            "description": "Search for code, APIs, and technical documentation through the platform's governed search provider (code-optimised where the provider supports it). Better than web_search for function signatures, library usage, and API docs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer"},
                    "include_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional domain allowlist for the search.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "lsp_go_to_definition": {
        "type": "function",
        "function": {
            "name": "lsp_go_to_definition",
            "description": "Go to definition of a symbol using LSP. Supported: .py, .ts, .tsx, .js, .go, .rs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "col": {"type": "integer", "description": "Column (default 1)"},
                },
                "required": ["path", "line"],
            },
        },
    },
    "lsp_find_references": {
        "type": "function",
        "function": {
            "name": "lsp_find_references",
            "description": "Find all references to a symbol using LSP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "col": {"type": "integer"},
                    "include_declaration": {"type": "boolean"},
                },
                "required": ["path", "line"],
            },
        },
    },
    "lsp_hover": {
        "type": "function",
        "function": {
            "name": "lsp_hover",
            "description": "Get type signature and documentation for a symbol using LSP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "col": {"type": "integer"},
                },
                "required": ["path", "line"],
            },
        },
    },
    "lsp_document_symbols": {
        "type": "function",
        "function": {
            "name": "lsp_document_symbols",
            "description": "List all symbols (functions, classes, variables) in a file using LSP.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    "lsp_diagnostics": {
        "type": "function",
        "function": {
            "name": "lsp_diagnostics",
            "description": "Get live diagnostics (errors/warnings) for a file using LSP. More accurate than check_file_syntax.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
}
