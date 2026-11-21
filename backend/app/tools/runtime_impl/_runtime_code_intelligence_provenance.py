"""Code intelligence provenance helpers shared by runtime tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Result list key -> provenance key naming the backends that produced the list items.
_ITEM_BACKEND_KEYS = (
    ("definitions", "definition_backends"),
    ("references", "reference_backends"),
    ("callers", "caller_backends"),
    ("outline", "outline_backends"),
)


def _non_empty_str_map(mapping: dict[Any, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in mapping.items() if str(key).strip() and str(value).strip()}


def _item_backends(items: list[Any]) -> list[str]:
    return sorted(
        {
            str(item.get("backend") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("backend") or "").strip()
        }
    )


def _code_intelligence_provenance(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    provenance: dict[str, Any] = {}
    repository = result.get("repository")
    if isinstance(repository, dict):
        effective_backends = repository.get("effective_backends")
        if isinstance(effective_backends, dict):
            provenance["repository_effective_backends"] = _non_empty_str_map(effective_backends)
    engines = result.get("engines")
    if isinstance(engines, dict):
        provenance["snapshot_engines"] = _non_empty_str_map(engines)
    search_backend = str(result.get("search_backend") or "").strip()
    if search_backend:
        provenance["search_backend"] = search_backend
    structure_backend = str(result.get("structure_backend") or "").strip()
    if structure_backend:
        provenance["structure_backend"] = structure_backend
    graph_backend = str(result.get("graph_backend") or "").strip()
    graph = result.get("graph")
    if not graph_backend and isinstance(graph, dict):
        graph_backend = str(graph.get("backend") or "").strip()
    if graph_backend:
        provenance["graph_backend"] = graph_backend
    for result_key, provenance_key in _ITEM_BACKEND_KEYS:
        if isinstance(result.get(result_key), list):
            backends = _item_backends(result[result_key])
            if backends:
                provenance[provenance_key] = backends
    return provenance


def _with_code_intelligence_provenance(
    result: dict[str, Any],
    *,
    provenance_builder: Callable[[dict[str, Any]], dict[str, Any]] = _code_intelligence_provenance,
) -> dict[str, Any]:
    payload = dict(result or {})
    provenance = provenance_builder(payload)
    if provenance:
        payload["provenance"] = provenance
    return payload
