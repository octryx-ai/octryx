"""Build decks strictly from a template's own layouts.

The composer never invents shapes or coordinates: every slide is created from a
layout that exists in the ``office_template_snapshot`` catalog, and every value
lands in a placeholder addressed by its ``idx``. When no layout in the template
can hold a plan entry, that is an explicit error listing the available layout
keys — never a silent approximation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .composer_plan import ComposerError, entry_requirements, select_layout
from .icon_embedding import IconEmbedder
from .icon_slots import place_layout_icons
from .package import write_pptx_copy
from .picture_safe_area import template_margin_emu
from .slide_filling import drop_sample_slides, fill_slide, layout_index
from .slide_gate import check_deck_quality

MAX_PLAN_ENTRIES = 200


def _check_inputs(template: Path, plan: list[dict[str, Any]]) -> None:
    if not template.is_file():
        raise ComposerError(f"template not found: {template}")
    if not isinstance(plan, list) or not plan:
        raise ComposerError("plan must be a non-empty list of slide entries")
    if len(plan) > MAX_PLAN_ENTRIES:
        raise ComposerError(f"plan has {len(plan)} entries, limit is {MAX_PLAN_ENTRIES}")


def _compose_slides(
    presentation: Any,
    template: Path,
    snapshot: dict[str, Any],
    plan: list[dict[str, Any]],
    output: Path,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Add one slide per plan entry and save the deck; returns layout keys, filled slots, icon findings."""
    layouts_by_part = layout_index(presentation)
    margin_emu = template_margin_emu(snapshot.get("layouts", []))

    used_layouts: list[str] = []
    applied: list[str] = []
    icon_findings: list[dict[str, Any]] = []
    with IconEmbedder(presentation, template) as embedder:
        for position, entry in enumerate(plan, start=1):
            if not isinstance(entry, dict):
                raise ComposerError(f"plan entry {position} is not an object")
            need = entry_requirements(entry)
            layout = select_layout(snapshot, entry, need)
            pptx_layout = layouts_by_part.get(str(layout.get("part")))
            if pptx_layout is None:
                raise ComposerError(
                    f"layout {layout.get('key')!r} ({layout.get('part')}) is in the snapshot "
                    "but not in the template package; rebuild the snapshot"
                )
            slide = presentation.slides.add_slide(pptx_layout)
            fill_slide(slide, layout, need, applied, margin_emu)
            icon_findings.extend(
                place_layout_icons(
                    embedder, slide, layout, need.get("icon_topics") or [], snapshot,
                    position, applied,
                )
            )
            used_layouts.append(str(layout.get("key")))

        presentation.save(str(output))
    return used_layouts, applied, icon_findings


def build_presentation_from_plan(
    template_path: str | Path,
    snapshot: dict[str, Any],
    plan: list[dict[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    """Compose ``plan`` into a deck built from ``template_path``'s layouts."""
    from pptx import Presentation  # local import: heavy optional dependency

    template = Path(template_path)
    _check_inputs(template, plan)

    output = Path(output_path)
    write_pptx_copy(template, output)
    presentation = Presentation(str(output))

    removed = drop_sample_slides(presentation)
    used_layouts, applied, icon_findings = _compose_slides(presentation, template, snapshot, plan, output)
    # The gate measures the artefact that was actually written and reports what
    # it finds. It never corrects a slide: the caller decides what to show.
    findings = icon_findings + check_deck_quality(snapshot, plan, output)
    return {
        "output_path": str(output),
        "slide_count": len(plan),
        "removed_sample_slides": removed,
        "layout_keys": used_layouts,
        "filled_slots": applied,
        "quality_findings": findings,
    }


__all__ = ["build_presentation_from_plan"]
