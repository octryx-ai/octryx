"""Deterministic post-composition quality gate for PowerPoint decks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .slide_brand_check import check_brand as _check_brand
from .slide_findings import finding as _finding
from .slide_findings import slide_content as _slide_content
from .slide_findings import sort_key as _sort_key
from .slide_picture_checks import (
    check_empty_content_next_to_picture,
    check_image_distortion,
    check_picture_covers_title,
    check_title_illegible,
)
from .slide_slot_checks import check_capacity, check_empty_required_slot, check_text_overflow

MAX_FINDINGS = 200

# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def check_deck_quality(
    snapshot: dict[str, Any], plan: list[dict[str, Any]], deck_path: str | Path
) -> list[dict[str, Any]]:
    """Measure a composed deck against the template's own evidence brief."""
    from pptx import Presentation  # local import: heavy optional dependency

    presentation = Presentation(str(deck_path))
    layouts = {str(layout.get("part")): layout for layout in snapshot.get("layouts", [])}
    theme = snapshot.get("theme") or {}
    slide_size = snapshot.get("slide_size") or {}
    findings: list[dict[str, Any]] = []

    for slide_index, slide in enumerate(presentation.slides, start=1):
        part = str(slide.slide_layout.part.partname).lstrip("/")
        layout = layouts.get(part)
        if layout is None:
            findings.append(
                _finding(
                    "unknown_layout", slide_index, part, None,
                    f"slide uses layout part {part!r}, which is not in the snapshot; "
                    "rebuild the snapshot from this template",
                )
            )
            continue
        entry = plan[slide_index - 1] if slide_index - 1 < len(plan) else {}
        entry = entry if isinstance(entry, dict) else {}
        texts, pictures = _slide_content(slide)

        findings.extend(
            check_picture_covers_title(slide_index, layout, texts, pictures, slide_size)
        )
        findings.extend(check_text_overflow(slide_index, layout, slide, texts))
        findings.extend(check_empty_required_slot(slide_index, layout, texts, pictures))
        findings.extend(
            check_empty_content_next_to_picture(slide_index, layout, texts, pictures)
        )
        findings.extend(check_title_illegible(slide_index, layout, texts, pictures))
        findings.extend(check_capacity(slide_index, layout, entry))
        findings.extend(check_image_distortion(slide_index, layout, pictures))
        findings.extend(_check_brand(slide_index, layout, slide, theme))

    findings.sort(key=_sort_key)
    return findings[:MAX_FINDINGS]


FINDING_CODES = (
    "capacity_exceeded",
    "empty_content_next_to_picture",
    "empty_required_slot",
    "image_distorted",
    "off_brand_font_or_color",
    "picture_covers_title",
    "text_overflow",
    "title_illegible",
    "unknown_layout",
)

__all__ = ["FINDING_CODES", "MAX_FINDINGS", "check_deck_quality"]
