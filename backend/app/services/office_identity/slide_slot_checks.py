"""Slide gate checks about slots: text overflow, empty required slots, layout capacity.

Every check measures the composed slide against the layout evidence and
returns findings; none of them changes a slide.
"""

from __future__ import annotations

import math
from typing import Any

from .composer_plan import ComposerError, entry_requirements
from .slide_findings import finding as _finding
from .slide_findings import is_picture as _is_picture
from .slide_findings import placeholder_idx as _placeholder_idx
from .template_snapshot import slots_by_role

_EMU_PER_PT = 12700

#: Average glyph advance as a fraction of the font size. 0.5 em is a
#: deliberately generous value for Arial-like faces (measured average is
#: ~0.52 em for mixed-case prose), so the line estimate errs on the low side.
_CHAR_WIDTH_EM = 0.5
#: Single-spaced line box, PowerPoint's own default.
_LINE_HEIGHT_EM = 1.2
#: Only report overflow when the estimate exceeds the slot by this much. The
#: metric is an estimate, so a marginal result stays silent by design.
_OVERFLOW_TOLERANCE = 1.15
#: Used only when neither the layout nor the master states a size.
_FALLBACK_FONT_PT = {"title": 24.0, "subtitle": 16.0, "content": 16.0}


def _autofit_shrinks(shape: Any) -> bool:
    """True only when the placeholder explicitly shrinks text to fit."""
    try:
        from pptx.enum.text import MSO_AUTO_SIZE

        return shape.text_frame.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    except Exception:  # pragma: no cover - optional attribute on odd shapes
        return False


def _estimated_lines(lines: list[str], width_emu: int, font_pt: float) -> int:
    char_width = font_pt * _CHAR_WIDTH_EM * _EMU_PER_PT
    per_line = max(1, int(width_emu / char_width)) if char_width > 0 else 1
    return sum(max(1, math.ceil(len(line) / per_line)) for line in lines)


def check_text_overflow(
    slide_index: int, layout: dict[str, Any], slide: Any, texts: dict[int, list[str]]
) -> list[dict[str, Any]]:
    shapes = {
        _placeholder_idx(shape): shape for shape in slide.shapes if not _is_picture(shape)
    }
    key = str(layout.get("key"))
    findings: list[dict[str, Any]] = []
    for slot in layout.get("slots", []):
        index = int(slot.get("idx") or 0)
        lines = texts.get(index)
        width = slot.get("w_emu")
        height = slot.get("h_emu")
        if not lines or not isinstance(width, int) or not isinstance(height, int):
            continue
        if width <= 0 or height <= 0:
            continue
        shape = shapes.get(index)
        if shape is not None and _autofit_shrinks(shape):
            continue  # PowerPoint shrinks the text instead of overflowing
        font_pt = slot.get("font_size_pt") or _FALLBACK_FONT_PT.get(str(slot.get("role")))
        if not font_pt:
            continue
        needed = _estimated_lines(lines, width, float(font_pt))
        needed_emu = needed * float(font_pt) * _LINE_HEIGHT_EM * _EMU_PER_PT
        if needed_emu <= height * _OVERFLOW_TOLERANCE:
            continue
        findings.append(
            _finding(
                "text_overflow",
                slide_index,
                key,
                index,
                f"slot idx{index} holds an estimated {needed} line(s) at {font_pt:g}pt "
                f"({needed_emu / _EMU_PER_PT:.0f}pt tall) but is only "
                f"{height / _EMU_PER_PT:.0f}pt high",
            )
        )
    return findings


def check_empty_required_slot(
    slide_index: int, layout: dict[str, Any], texts: dict[int, list[str]],
    pictures: dict[int | None, Any],
) -> list[dict[str, Any]]:
    key = str(layout.get("key"))
    findings: list[dict[str, Any]] = []
    for slot in slots_by_role(layout, "title"):
        index = int(slot.get("idx") or 0)
        if not texts.get(index):
            findings.append(
                _finding(
                    "empty_required_slot", slide_index, key, index,
                    f"title slot idx{index} of layout {key!r} stayed empty",
                )
            )
    # A content slot left empty next to a filled picture is intentional: that
    # is what a diagram on a "content left, image right" layout looks like.
    # A title slide's extra text line is an optional strapline, not content.
    content_slots = [] if layout.get("content_shape") == "title_slide" else slots_by_role(layout, "content")
    if content_slots and not any(
        texts.get(int(slot.get("idx") or 0)) for slot in content_slots
    ) and not pictures:
        findings.append(
            _finding(
                "empty_required_slot", slide_index, key, None,
                f"layout {key!r} offers {len(content_slots)} content slot(s) but the "
                "slide carries neither text nor a picture in them",
            )
        )
    return findings


def check_capacity(
    slide_index: int, layout: dict[str, Any], entry: dict[str, Any]
) -> list[dict[str, Any]]:
    capacity = layout.get("capacity") or {}
    key = str(layout.get("key"))
    try:
        need = entry_requirements(entry)
    except ComposerError:
        return []  # an unusable plan entry is the composer's error, not the gate's
    findings: list[dict[str, Any]] = []
    for label, want, have in (
        ("content unit", need["units"], int(capacity.get("content_units") or 0)),
        ("picture", need["pictures"], int(capacity.get("picture_slots") or 0)),
    ):
        if want > have:
            findings.append(
                _finding(
                    "capacity_exceeded", slide_index, key, None,
                    f"plan entry needs {want} {label}(s) but layout {key!r} holds {have}",
                )
            )
    return findings


__all__ = ["check_capacity", "check_empty_required_slot", "check_text_overflow"]
