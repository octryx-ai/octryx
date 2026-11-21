"""Code-intelligence, git-intelligence and review services of the code tools, read from their defining modules.

Each name is looked up on its owning module at call time, so a test that replaces a service on that module
reaches the tool.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

_CODE_INTELLIGENCE_OWNERS = {
    "build_impact_analysis": "app.services.code_intelligence.queries",
    "detect_code_intelligence_capabilities": "app.services.code_intelligence.storage_capabilities",
    "find_symbol_callers": "app.services.code_intelligence.queries",
    "find_symbol_definition": "app.services.code_intelligence.queries",
    "find_symbol_references": "app.services.code_intelligence.queries",
    "get_code_graph_affected": "app.services.code_intelligence.graph_analytics",
    "get_code_graph_callees": "app.services.code_intelligence.graph_queries",
    "get_code_graph_context": "app.services.code_intelligence.graph_context",
    "get_code_graph_files": "app.services.code_intelligence.graph_path_queries",
    "get_code_graph_god_nodes": "app.services.code_intelligence.graph_analytics",
    "get_code_graph_neighbors": "app.services.code_intelligence.graph_queries",
    "get_code_graph_node": "app.services.code_intelligence.graph_queries",
    "get_code_graph_stats": "app.services.code_intelligence.graph_analytics",
    "get_code_graph_status": "app.services.code_intelligence.graph_queries",
    "get_code_graph_trace": "app.services.code_intelligence.graph_path_queries",
    "get_file_outline": "app.services.code_intelligence.outline_queries",
    "get_graph_summary": "app.services.code_intelligence.queries",
    "run_code_index": "app.services.code_intelligence.indexing",
    "search_repository_code": "app.services.code_intelligence.queries",
}

_RUNTIME_SERVICE_OWNERS = {
    "git_change_summary": "app.services.git_intelligence_service",
    "git_conflict_predictor": "app.services.git_intelligence_service",
    "git_coupling_map": "app.services.git_intelligence_service",
    "git_file_intelligence": "app.services.git_intelligence_service",
    "git_function_blame": "app.services.git_intelligence_service",
    "git_hotspot_analysis": "app.services.git_intelligence_service",
    "git_knowledge_extract": "app.services.git_intelligence_service",
    "git_pr_context": "app.services.git_intelligence_service",
    "self_review_workspace_diff": "app.services.review.service",
    "build_pull_request_description": "app.services.review.service",
}


def resolve_code_intelligence_service(function_name: str) -> Callable[..., Any]:
    """The code-intelligence function ``function_name``, read from its defining module."""

    return getattr(importlib.import_module(_CODE_INTELLIGENCE_OWNERS[function_name]), function_name)


def resolve_runtime_service(function_name: str) -> Callable[..., Any]:
    """The git-intelligence or review function ``function_name``, read from its defining module."""

    return getattr(importlib.import_module(_RUNTIME_SERVICE_OWNERS[function_name]), function_name)
