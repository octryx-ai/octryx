from __future__ import annotations

from typing import Any

from app.services.tool_result_compression.budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from app.services.tool_result_compression.config import clamp_config_int

from ..prompt_catalog import render_prompt

_FULL_DIAGRAM_RESULT_TOKEN_BUDGET = 50000


def _compress_kubernetes_topology_snapshot(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if "topology_summary" not in result and "diagram_brief" not in result:
        return None

    max_warnings = clamp_config_int(config, "max_warnings", default=20, minimum=0, maximum=100)
    compact = {
        "source": result.get("source"),
        "generated_at": result.get("generated_at"),
        "scope": _compact_scope(result.get("scope")),
        "topology_summary": _compact_topology_summary(result.get("topology_summary")),
        "diagram_brief": _compact_diagram_brief(result.get("diagram_brief"), config),
        "warning_count": len(result.get("warnings") or []),
        "warnings": [str(item)[:500] for item in (result.get("warnings") or [])[:max_warnings]],
        "answer_guidance": render_prompt("tool_guard.compression.kubernetes.guidance"),
        "compression_note": render_prompt("tool_guard.compression.kubernetes.note"),
    }
    if str((compact.get("diagram_brief") or {}).get("mode") or "").strip().lower() == "full":
        compact[COMPACT_RESULT_TOKEN_BUDGET_KEY] = clamp_config_int(
            config,
            "full_diagram_result_token_budget",
            default=_FULL_DIAGRAM_RESULT_TOKEN_BUDGET,
            minimum=3000,
            maximum=_FULL_DIAGRAM_RESULT_TOKEN_BUDGET,
        )
    return compact


def _compact_scope(value: Any) -> dict[str, Any]:
    scope = value if isinstance(value, dict) else {}
    return {
        "namespace": scope.get("namespace"),
        "all_namespaces": bool(scope.get("all_namespaces")),
    }


def _compact_topology_summary(value: Any) -> dict[str, Any]:
    summary = value if isinstance(value, dict) else {}
    node_counts = summary.get("node_counts_by_type") if isinstance(summary.get("node_counts_by_type"), dict) else {}
    return {
        "resource_node_count": summary.get("resource_node_count"),
        "edge_count": summary.get("edge_count"),
        "selected_resource_node_count": summary.get("selected_resource_node_count"),
        "selected_edge_count": summary.get("selected_edge_count"),
        "node_counts_by_type": dict(sorted(node_counts.items())),
    }


def _compact_diagram_brief(value: Any, config: dict[str, Any]) -> dict[str, Any]:
    brief = value if isinstance(value, dict) else {}
    max_nodes = clamp_config_int(config, "max_diagram_nodes", default=1000, minimum=0, maximum=5000)
    max_edges = clamp_config_int(config, "max_diagram_edges", default=2000, minimum=0, maximum=10000)
    selected_nodes = [item for item in (brief.get("selected_nodes") or []) if isinstance(item, dict)]
    selected_edges = [item for item in (brief.get("selected_edges") or []) if isinstance(item, dict)]
    return {
        "mode": brief.get("mode"),
        "selected_nodes": selected_nodes[:max_nodes],
        "selected_edges": selected_edges[:max_edges],
        "omitted_node_count": _safe_int(brief.get("omitted_node_count"), default=0)
        + max(0, len(selected_nodes) - max_nodes),
        "omitted_edge_count": _safe_int(brief.get("omitted_edge_count"), default=0)
        + max(0, len(selected_edges) - max_edges),
    }


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = ["_compress_kubernetes_topology_snapshot"]
