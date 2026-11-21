"""Diagram-owned tool result compaction for model context.

Owned by the diagram tool domain (``app.tools.diagram``): the agent engine
core carries no shape-library payload knowledge and resolves this compactor
through the generic registry in
``app.agent.engine.messages._tool_compaction_registry``.
"""

from __future__ import annotations

from typing import Any

from ..agent.engine.messages._engine_message_helpers import _truncate_for_model
from .tool_names import ToolName


def compact_shape_library_result(result: dict[str, Any]) -> dict[str, Any]:
    matched_shapes = []
    for item in (result.get("matched_shapes") or [])[:20]:
        if not isinstance(item, dict):
            continue
        matched_shapes.append(
            {
                "requested": item.get("requested"),
                "shape": item.get("shape"),
                "match_type": item.get("match_type"),
                "alternatives": (item.get("alternatives") or [])[:5],
            }
        )
    return {
        "library": result.get("library"),
        "prefix": result.get("prefix"),
        "usage_xml": _truncate_for_model(result.get("usage_xml") or "", 400),
        "shape_count": result.get("shape_count"),
        "requested_shape_names": (result.get("requested_shape_names") or [])[:20],
        "matched_shapes": matched_shapes,
        "missing_shape_names": (result.get("missing_shape_names") or [])[:20],
    }


def register_result_compactors() -> None:
    """Register the diagram tool result compactors with the engine registry."""
    from ..agent.engine.messages._tool_compaction_registry import register_tool_result_compactor

    register_tool_result_compactor(ToolName.GET_SHAPE_LIBRARY, compact_shape_library_result)
