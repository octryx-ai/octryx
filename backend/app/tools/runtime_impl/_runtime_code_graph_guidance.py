"""Agent guidance attached to code graph results: when snippets can be trusted and which files are stale."""

from __future__ import annotations

from typing import Any

from ._runtime_cli_helpers import _with_code_intelligence_provenance


def _with_graph_agent_guidance(result: dict[str, Any]) -> dict[str, Any]:
    payload = _with_code_intelligence_provenance(result)
    guidance: list[str] = []
    graph = payload.get("graph")
    staleness_warnings = []
    if isinstance(graph, dict):
        staleness_warnings = [item for item in graph.get("staleness_warnings") or [] if isinstance(item, dict)]
    if _has_source_chunk(payload):
        guidance.append(
            "Returned source chunks are line-numbered graph snippets; do not re-read them unless the graph is stale "
            "or surrounding context is needed."
        )
    if staleness_warnings:
        stale_paths = sorted({str(item.get("path") or "").strip() for item in staleness_warnings if item.get("path")})
        if stale_paths:
            guidance.append(
                "Graph index is stale for these files; read them directly before editing or relying on snippets: "
                + ", ".join(stale_paths[:10])
            )
        else:
            guidance.append("Graph index has staleness warnings; check freshness before relying on snippets.")
    if guidance:
        existing = payload.get("agent_guidance")
        payload["agent_guidance"] = [*existing, *guidance] if isinstance(existing, list) else guidance
    return payload


def _has_source_chunk(value: Any) -> bool:
    if isinstance(value, dict):
        if "source_chunk" in value and value.get("source_chunk"):
            return True
        return any(_has_source_chunk(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_source_chunk(item) for item in value)
    return False
