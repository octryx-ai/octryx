"""Deterministic evidence-diagram set for the deck, built from the snapshot.

The deck must not depend on how many times the model happened to call
``create_diagram``: a run that drew the overview once left a deck with a single
diagram slide, while the detail set (service inventory, per-tier/per-app views)
was never rendered. This module derives the full set — overview first, then the
substantive detail diagrams — from the AWS topology snapshot using the SAME
builders the diagram pipeline uses (no second render path), renders each to PNG,
and hands them to the planner as one slide per diagram.

It is used only when the snapshot carries a ``diagram_brief`` (the selection the
renderer draws from). Without one it yields nothing and the caller falls back to
the diagrams the turn already produced.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger("uvicorn.error")

_PNG_RENDER_SCALE = 2
# The canonical AWS evidence contract the enforcement uses; empty topic keeps
# the builders' own titles ("AWS Topology Overview", "… Service inventory", …).
_CONTRACT = {"diagram_source": "aws_topology_snapshot", "topic": ""}


def _slug(value: str, fallback: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:48] or fallback


def _full_aws_shape_library() -> dict[str, Any]:
    """The aws4 library with every shape matched, so no icon degrades to a stub.

    The turn history keeps only a 20-shape compacted library (fine for the
    model); rendering the full topology needs every type mapped, so load it
    fresh rather than reuse the compacted copy.
    """
    from .._diagram_shape_library import _SHAPE_LIBRARY_DIR, _extract_shape_library_metadata, load_shape_library

    content = (_SHAPE_LIBRARY_DIR / "aws4.md").read_text(encoding="utf-8")
    _prefix, _usage, available = _extract_shape_library_metadata(content)
    return load_shape_library("aws4", list(available))


def _evidence_diagram_calls(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Overview + inventory + substantive detail diagrams, as create_diagram calls."""
    from ...services.diagrams.aws_topology_diagram import (
        build_aws_topology_detail_diagram_tool_calls,
        build_aws_topology_diagram_tool_call,
    )

    brief = snapshot.get("diagram_brief") if isinstance(snapshot, dict) else None
    if not isinstance(brief, dict) or not brief.get("selected_nodes"):
        return []
    shape_library = _full_aws_shape_library()
    calls = list(build_aws_topology_diagram_tool_call(dict(_CONTRACT), snapshot, shape_library, None) or [])
    calls += list(
        build_aws_topology_detail_diagram_tool_calls(dict(_CONTRACT), snapshot, shape_library, None) or []
    )
    return calls


async def evidence_diagram_images(
    snapshot: dict[str, Any],
    *,
    output_dir: Path,
    max_images: int,
) -> tuple[list[dict[str, str]], list[str]]:
    """Render the deterministic evidence-diagram set to PNG, one entry per diagram.

    Returns ``(images, warnings)`` in the same shape the planner consumes from
    the turn's own diagrams. Empty when the snapshot has no ``diagram_brief``.
    """
    from ...services.diagram_export_service import (
        DiagramRenderError,
        DiagramRendererUnavailableError,
        render_diagram_png,
    )

    calls = _evidence_diagram_calls(snapshot)
    images: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_titles: set[str] = set()

    for index, call in enumerate(calls):
        raw_args = (call.get("function") or {}).get("arguments")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except (TypeError, ValueError):
            continue
        title = str(args.get("title") or "").strip()
        xml = str(args.get("xml") or "").strip()
        if not xml or title in seen_titles:
            continue
        seen_titles.add(title)
        # The builders emit bare mxCell elements — the same shape create_diagram
        # receives and wraps before it stores a diagram. Wrap them into a full
        # mxGraphModel document so the renderer accepts them.
        from ..diagram import _wrap_cells

        xml = _wrap_cells(xml)
        if len(images) >= max_images:
            warnings.append(
                f"diagram '{title}' omitted: only {max_images} diagram slides are composed"
            )
            continue
        diagram_id = f"evidence-{index:02d}-{_slug(title, 'diagram')}"
        try:
            png_bytes = await asyncio.to_thread(
                render_diagram_png, diagram_id=diagram_id, diagram_xml=xml, scale=_PNG_RENDER_SCALE
            )
        except DiagramRendererUnavailableError as exc:
            # No renderer at all: give up on the whole set so the caller can fall
            # back to the turn's own diagrams rather than a half-empty set.
            warnings.append(f"renderer_unavailable: evidence diagram set not rendered ({exc})")
            return [], warnings
        except DiagramRenderError as exc:
            warnings.append(f"render_failed: diagram '{title}' not embedded ({exc})")
            continue
        image_path = output_dir / f"diagram-{diagram_id}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(png_bytes)
        images.append({"path": str(image_path), "title": title, "diagram_id": diagram_id})

    _logger.info("presentation evidence diagrams: rendered=%d warnings=%d", len(images), len(warnings))
    return images, warnings
