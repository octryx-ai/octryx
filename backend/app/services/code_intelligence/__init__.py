"""Canonical package exports for code intelligence services."""

from __future__ import annotations

import importlib
from typing import Any

_PUBLIC_MODULES = frozenset(
    {
        "graph",
        "graph_analytics",
        "graph_admin",
        "graph_context",
        "graph_queries",
        "graph_query_support",
        "indexing",
        "outline",
        "outline_queries",
        "process",
        "queries",
        "repository",
        "structure",
        "symbol_analysis",
    }
)

_PUBLIC_FUNCTION_MODULES = {
    "_build_snapshot": "app.services.code_intelligence.indexing",
    "get_code_graph_admin_status": "app.services.code_intelligence.graph_admin",
    "get_repository_snapshot": "app.services.code_intelligence.indexing",
    "run_code_index": "app.services.code_intelligence.indexing",
}


def __getattr__(name: str) -> Any:
    if name in _PUBLIC_MODULES:
        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    if name in _PUBLIC_FUNCTION_MODULES:
        module = importlib.import_module(_PUBLIC_FUNCTION_MODULES[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _PUBLIC_MODULES | set(_PUBLIC_FUNCTION_MODULES))


__all__ = sorted([*_PUBLIC_MODULES, *_PUBLIC_FUNCTION_MODULES])
