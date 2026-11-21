"""Deterministic budget enforcement for diagram-path compact results.

A compact tool result that carries a ``diagram_brief`` feeds the
evidence-backed diagram pipeline (``_loop_evidence_diagrams`` /
``enforce_evidence_backed_diagrams``): the loop only runs the deterministic
diagram planner when the compact result in the turn history contains a
``diagram_brief`` dict. The generic hard-cap fallback in ``budget.py``
replaces over-budget results with a brief-less ``_hard_capped`` stub, which
silently disabled that pipeline (the model then free-draws).

This module replaces that stub for diagram-path results: instead of dropping
the brief, it deterministically shrinks the ``selected_nodes`` /
``selected_edges`` selection (and, if needed, the sibling payload) until the
result fits the budget. The output ALWAYS retains a bounded ``diagram_brief``.
"""

from __future__ import annotations

from typing import Any

from .support import _estimate_tokens

# Shrink ladder for the diagram selection; strictly decreasing so the
# enforcement is deterministic and always terminates.
_SELECTION_LIMIT_LADDER = (40, 32, 24, 16, 12, 8, 6, 4)
_MINIMUM_SELECTION_LIMIT = _SELECTION_LIMIT_LADDER[-1]
# Sibling keys that stay meaningful on a heavily capped diagram result.
_ESSENTIAL_SIBLING_KEYS = (
    "account_id",
    "region",
    "generated_at",
    "scope",
    "answer_guidance",
    "compression_note",
)
_MAX_ESSENTIAL_STRING_CHARS = 500
_MINIMAL_NODE_LABEL_CHARS = 120


def has_diagram_brief(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("diagram_brief"), dict)


def enforce_diagram_compact_result_budget(value: dict[str, Any], *, token_budget: int) -> dict[str, Any]:
    """Cap a diagram-path compact result without ever dropping ``diagram_brief``.

    Phase 1 keeps every sibling key and shrinks only the diagram selection.
    Phase 2 additionally reduces siblings to the essential set. The final
    fallback strips node attributes and truncates labels at the smallest
    selection limit and is returned unconditionally: a brief-less stub is
    never produced on this path.
    """
    brief = dict(value.get("diagram_brief") or {})
    for sibling_keys in (None, _ESSENTIAL_SIBLING_KEYS):
        for limit in _SELECTION_LIMIT_LADDER:
            candidate = _capped_candidate(
                value,
                _shrunk_brief(brief, max_nodes=limit, max_edges=limit),
                sibling_keys=sibling_keys,
            )
            if _estimate_tokens(candidate) <= token_budget:
                return candidate
    minimal_brief = _shrunk_brief(
        brief,
        max_nodes=_MINIMUM_SELECTION_LIMIT,
        max_edges=_MINIMUM_SELECTION_LIMIT,
        minimal_nodes=True,
    )
    return _capped_candidate(value, minimal_brief, sibling_keys=_ESSENTIAL_SIBLING_KEYS)


def _capped_candidate(
    value: dict[str, Any],
    brief: dict[str, Any],
    *,
    sibling_keys: tuple[str, ...] | None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {}
    for key, item in value.items():
        if key == "diagram_brief":
            continue
        if sibling_keys is not None:
            if key not in sibling_keys:
                continue
            item = _bounded_essential_value(item)
        candidate[str(key)] = item
    candidate["diagram_brief"] = brief
    candidate["_hard_capped"] = True
    return candidate


def _shrunk_brief(
    brief: dict[str, Any],
    *,
    max_nodes: int,
    max_edges: int,
    minimal_nodes: bool = False,
) -> dict[str, Any]:
    nodes = [node for node in (brief.get("selected_nodes") or []) if isinstance(node, dict)]
    edges = [edge for edge in (brief.get("selected_edges") or []) if isinstance(edge, dict)]
    kept_nodes = nodes[:max_nodes]
    node_keys = {
        str(node.get("ref") or node.get("id") or "")
        for node in kept_nodes
        if str(node.get("ref") or node.get("id") or "").strip()
    }
    kept_edges = [edge for edge in edges if _edge_endpoints_kept(edge, node_keys)][:max_edges]
    if minimal_nodes:
        kept_nodes = [_minimal_node(node) for node in kept_nodes]
    shrunk = dict(brief)
    shrunk["selected_nodes"] = kept_nodes
    shrunk["selected_edges"] = kept_edges
    if len(kept_nodes) < len(nodes) or len(kept_edges) < len(edges):
        notes = [str(note) for note in (brief.get("notes") or []) if str(note or "").strip()]
        notes.append(
            "diagram_brief reduced to fit the compact result budget: "
            f"kept {len(kept_nodes)}/{len(nodes)} selected nodes and {len(kept_edges)}/{len(edges)} selected edges."
        )
        shrunk["notes"] = notes
    return shrunk


def _edge_endpoints_kept(edge: dict[str, Any], node_keys: set[str]) -> bool:
    source = str(edge.get("source_ref") or edge.get("source") or "").strip()
    target = str(edge.get("target_ref") or edge.get("target") or "").strip()
    return bool(source) and bool(target) and source in node_keys and target in node_keys


def _minimal_node(node: dict[str, Any]) -> dict[str, Any]:
    minimal = {
        key: node.get(key)
        for key in ("ref", "id", "type", "label", "service", "region")
        if key in node
    }
    label = str(minimal.get("label") or "")
    if len(label) > _MINIMAL_NODE_LABEL_CHARS:
        minimal["label"] = label[:_MINIMAL_NODE_LABEL_CHARS]
    return minimal


def _bounded_essential_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_ESSENTIAL_STRING_CHARS:
        return value[:_MAX_ESSENTIAL_STRING_CHARS]
    if isinstance(value, list):
        return [_bounded_essential_value(item) for item in value[:10]]
    if isinstance(value, dict):
        return {str(key): _bounded_essential_value(item) for key, item in list(value.items())[:20]}
    return value


__all__ = ["enforce_diagram_compact_result_budget", "has_diagram_brief"]
