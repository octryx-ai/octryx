"""Tool definitions for knowledge domain."""

from __future__ import annotations

import copy

from .knowledge_packs import KNOWLEDGE_PACK_DEFINITIONS

_KNOWLEDGE_RETRIEVAL_DEFINITIONS: dict[str, dict] = {
    "acknowledge": {
        "type": "function",
        "function": {
            "name": "acknowledge",
            "description": "Acknowledge a PagerDuty incident or OpsGenie alert",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "alert_id": {"type": "string", "description": "Alias for incident_id"},
                    "message": {"type": "string"},
                    "identifier_type": {"type": "string"},
                    "from_email": {"type": "string"},
                },
            },
        },
    },
    "knowledge_retrieve": {
        "type": "function",
        "function": {
            "name": "knowledge_retrieve",
            "description": (
                "Hybrid retrieval over the knowledge base: relevant passages (chunks), graph entities "
                "with their relationships, and community summaries — in one governed call. "
                "Modes: 'mix' (default, passages + graph + communities), 'naive' (passages only), "
                "'local' (graph entities/relations only), 'global' (community summaries for "
                "whole-system questions). Returns a ready-to-use 'context' block plus structured results. "
                "Prefer this for questions about how parts of the system relate (services, components, "
                "people, tickets, infrastructure)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "mode": {"type": "string", "enum": ["mix", "naive", "local", "global"]},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "query_document_knowledge": {
        "type": "function",
        "function": {
            "name": "query_document_knowledge",
            "description": "Search indexed document chunks to answer questions about uploaded or ingested PDF/Office/text documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "document_id": {
                        "type": "string",
                        "description": "Optional source id returned by ingest_document_source",
                    },
                    "source_id": {"type": "string", "description": "Alias for document_id"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    "git_knowledge_extract": {
        "type": "function",
        "function": {
            "name": "git_knowledge_extract",
            "description": "Compress recent git history into a codebase-history knowledge payload and optionally persist it",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string"},
                    "project_id": {"type": "string"},
                    "scope": {"type": "string"},
                    "extract_types": {"type": "array", "items": {"type": "string"}},
                    "days": {"type": "integer"},
                },
            },
        },
    },
    "fetch_and_save_knowledge": {
        "type": "function",
        "function": {
            "name": "fetch_and_save_knowledge",
            "description": (
                "Fetch up-to-date documentation from an external source (Context7, URL, or any MCP "
                "server) and return the content with its source_uri, so it can be turned into pack "
                "items. Nothing is stored."
            ),
            "parameters": {
                "type": "object",
                "required": ["source", "query"],
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source type: 'context7' for official library docs via Context7 MCP, 'url' for any URL, 'mcp' for any registered MCP server.",
                        "enum": ["context7", "url", "mcp"],
                    },
                    "query": {
                        "type": "string",
                        "description": "For context7: library name (e.g. 'java', 'spring-boot'). For url: the URL. For mcp: 'server_name/tool_name'.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional sub-topic or focus area within the library/URL (e.g. 'new features', 'migration', 'breaking changes').",
                    },
                },
            },
        },
    },
    "build_engineering_knowledge_pack": {
        "type": "function",
        "function": {
            "name": "build_engineering_knowledge_pack",
            "description": (
                "Create a reviewable Engineering Knowledge Pack draft for exact source and target versions "
                "from archived source evidence and quality gates. Pass the versions as structured fields; "
                "they are not read from prompt text. The pack is submitted for human review and is not "
                "published automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stack_key": {
                        "type": "string",
                        "enum": ["java", "java-spring", "python"],
                        "description": "Optional; derived from the version coordinates when omitted.",
                    },
                    "source_versions": {
                        "type": "object",
                        "description": "Exact source versions, e.g. {'java': '21', 'spring_boot': '3.4'}.",
                    },
                    "target_versions": {
                        "type": "object",
                        "description": "Exact target versions, e.g. {'java': '25', 'spring_boot': '4.0.3'}.",
                    },
                    "source_overrides": {"type": "object"},
                    "allow_network": {"type": "boolean"},
                    "max_download_bytes": {"type": "integer"},
                    "source_policy": {"type": "object"},
                    "freshness_policy": {"type": "object"},
                    "publish_policy": {"type": "object"},
                    "review_policy": {"type": "object"},
                },
                "required": ["target_versions"],
            },
        },
    },
    "search_engineering_knowledge": {
        "type": "function",
        "function": {
            "name": "search_engineering_knowledge",
            "description": (
                "Search governed Engineering Knowledge Graph facts for coding and investigation. Results are "
                "compact, evidence-backed, and filtered by scope, trust, classification, and validity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "node_types": {"type": "array", "items": {"type": "string"}},
                    "node_type": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "code_repository_id": {"type": "string"},
                    "classification": {"type": "string"},
                    "include_silver": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_repository_patterns": {
        "type": "function",
        "function": {
            "name": "get_repository_patterns",
            "description": (
                "Retrieve governed fix, failure, policy, technology, and runtime patterns for a repository or "
                "project before planning code changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "code_repository_id": {"type": "string"},
                    "include_silver": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_vulnerability_fix_knowledge": {
        "type": "function",
        "function": {
            "name": "get_vulnerability_fix_knowledge",
            "description": (
                "Retrieve governed vulnerability and fix-pattern knowledge for CVEs, packages, dependencies, "
                "and affected technologies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "cve": {"type": "string"},
                    "package": {"type": "string"},
                    "dependency": {"type": "string"},
                    "technology": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "include_silver": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_pipeline_failure_patterns": {
        "type": "function",
        "function": {
            "name": "get_pipeline_failure_patterns",
            "description": "Retrieve governed build, CI/CD, and pipeline failure patterns with source evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "pipeline": {"type": "string"},
                    "stage": {"type": "string"},
                    "include_silver": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_reviewer_expertise": {
        "type": "function",
        "function": {
            "name": "get_reviewer_expertise",
            "description": (
                "Retrieve governed reviewer, team, ownership, and technology expertise facts for review routing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "reviewer": {"type": "string"},
                    "team": {"type": "string"},
                    "technology": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "include_silver": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
}


def get_knowledge_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for knowledge tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**_KNOWLEDGE_RETRIEVAL_DEFINITIONS, **KNOWLEDGE_PACK_DEFINITIONS})
