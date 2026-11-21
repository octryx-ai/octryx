"""Tool definitions for code-quality config, project design context and code search."""

from __future__ import annotations

# ruff: noqa: E501

CODE_INTELLIGENCE_DEFINITIONS: dict[str, dict] = {
    "get_repo_code_quality_config": {
        "type": "function",
        "function": {
            "name": "get_repo_code_quality_config",
            "description": "Detect repo-specific code quality settings for tests, linting and formatting",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                },
            },
        },
    },
    "code_intelligence_status": {
        "type": "function",
        "function": {
            "name": "code_intelligence_status",
            "description": "Show which repository code-intelligence backends are currently available",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "list_project_design_artifacts": {
        "type": "function",
        "function": {
            "name": "list_project_design_artifacts",
            "description": "List the current project's structured design artifacts such as outcome briefs, PRDs, acceptance criteria, ADRs and definition-of-done entries",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "artifact_kind": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
        },
    },
    "get_project_design_context": {
        "type": "function",
        "function": {
            "name": "get_project_design_context",
            "description": "Return the current project's design context, artifact coverage and recommended artifact template list",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "artifact_kind": {"type": "string"},
                },
            },
        },
    },
    "get_project_design_readiness": {
        "type": "function",
        "function": {
            "name": "get_project_design_readiness",
            "description": "Return the current project's required design-artifact readiness, blockers and repository traceability coverage",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
            },
        },
    },
    "get_project_design_traceability": {
        "type": "function",
        "function": {
            "name": "get_project_design_traceability",
            "description": "Return the current project's artifact-to-task, PR and release traceability summary",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
            },
        },
    },
    "run_design_trace_sync_workflow": {
        "type": "function",
        "function": {
            "name": "run_design_trace_sync_workflow",
            "description": "Run a configured project design-trace sync workflow for releases or checkpoints",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "limit_per_repository": {"type": "integer"},
                },
                "required": ["workflow_id"],
            },
        },
    },
    "code_index_repository": {
        "type": "function",
        "function": {
            "name": "code_index_repository",
            "description": "Build or refresh the persistent repository code-intelligence index",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "force": {"type": "boolean"},
                },
                "required": ["repository_id"],
            },
        },
    },
    "code_search": {
        "type": "function",
        "function": {
            "name": "code_search",
            "description": "Search inside the current repository using persistent code intelligence and text fallback",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "code_symbol_definition": {
        "type": "function",
        "function": {
            "name": "code_symbol_definition",
            "description": "Resolve likely definitions for a symbol in the current repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["symbol"],
            },
        },
    },
    "code_references": {
        "type": "function",
        "function": {
            "name": "code_references",
            "description": "Find references for a symbol in the current repository",
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
    "code_callers": {
        "type": "function",
        "function": {
            "name": "code_callers",
            "description": "Find likely call sites for a symbol in the current repository",
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
    "code_file_outline": {
        "type": "function",
        "function": {
            "name": "code_file_outline",
            "description": "Return the structural outline and code chunks for a repository file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                },
            },
        },
    },
    "code_graph_summary": {
        "type": "function",
        "function": {
            "name": "code_graph_summary",
            "description": "Return the repository architecture graph summary and artifact metadata",
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_id": {"type": "string"},
                    "cwd": {"type": "string"},
                },
            },
        },
    },
}
