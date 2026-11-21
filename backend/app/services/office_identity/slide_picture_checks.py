"""Slide gate checks about pictures: what they cover, what sits beside them, their aspect.

Every check measures the geometry the composer actually produced and returns
findings; none of them changes a slide.
"""

from __future__ import annotations

from typing import Any

from .layout_backdrop import is_light_color
from .picture_safe_area import has_title_backdrop
from .slide_findings import finding as _finding
from .slide_findings import picture_items as _picture_items
from .slide_findings import shape_rect as _shape_rect
from .slot_coverage import BRAND_ROLES, COVER_RATIO, FULL_BLEED_AREA_RATIO, covered_fraction
from .template_snapshot import slots_by_role

#: Rendered vs. source aspect ratio may differ by this much before a picture
#: counts as distorted (rounding in EMU arithmetic alone reaches ~0.5 %).
_ASPECT_TOLERANCE = 0.02


def _brand_slots(layout: dict[str, Any]) -> list[dict[str, Any]]:
    chrome = [slot for slot in layout.get("chrome_slots", ()) if isinstance(slot, dict)]
    return [
        slot
        for slot in list(layout.get("slots", ())) + chrome
        if str(slot.get("role")) in BRAND_ROLES
    ]


def check_picture_covers_title(
    slide_index: int,
    layout: dict[str, Any],
    texts: dict[int, list[str]],
    pictures: dict[int | None, Any],
    slide_size: dict[str, int],
) -> list[dict[str, Any]]:
    """Measured against the geometry the composer actually produced.

    The layout's ``full_bleed`` flag drives *selection*; it must not drive the
    verdict, because a full-bleed slot filled in inset mode no longer covers
    anything. Like the diagram gate, this measures what was rendered.
    """
    title_slots = slots_by_role(layout, "title")
    if not any(texts.get(int(slot.get("idx") or 0)) for slot in title_slots):
        return []
    slide_area = int(slide_size.get("width_emu") or 0) * int(slide_size.get("height_emu") or 0)
    protected = _brand_slots(layout)
    key = str(layout.get("key"))
    findings: list[dict[str, Any]] = []
    for index, picture in _picture_items(pictures):
        rect = _shape_rect(picture)
        if rect is None:
            continue
        hidden = sorted(
            int(slot.get("idx") or 0)
            for slot in protected
            if covered_fraction(rect, slot) >= COVER_RATIO
        )
        ratio = (rect["w_emu"] * rect["h_emu"]) / slide_area if slide_area > 0 else 0.0
        if ratio < FULL_BLEED_AREA_RATIO and not hidden:
            continue
        detail = f"; it covers slot(s) {hidden}" if hidden else ""
        findings.append(
            _finding(
                "picture_covers_title",
                slide_index,
                key,
                index,
                f"picture at slot idx{index} spans {ratio * 100:.0f}% of the slide while "
                f"the slide carries a title{detail} — title, brand background and logo "
                "are not visible",
            )
        )
    return findings


def check_title_illegible(
    slide_index: int,
    layout: dict[str, Any],
    texts: dict[int, list[str]],
    pictures: dict[int | None, Any],
) -> list[dict[str, Any]]:
    """A light title with nothing behind it is invisible, not merely subtle.

    A full-screen picture layout often declares a light title because the design
    assumes a photograph underneath. Move the picture away (as the inset does) and the
    title becomes white on the white master background — the rendered proof
    showed a slide with no title at all and no other finding. A layout that
    paints its own title backdrop, or whose title inherits the master colour,
    is fine.
    """
    if has_title_backdrop(layout):
        return []
    findings: list[dict[str, Any]] = []
    for slot in slots_by_role(layout, "title"):
        index = int(slot.get("idx") or 0)
        if not texts.get(index) or not is_light_color(slot.get("font_color")):
            continue
        behind = any(
            covered_fraction(rect, slot) >= COVER_RATIO
            for rect in (_shape_rect(picture) for picture in pictures.values())
            if rect is not None
        )
        if behind:
            continue  # a picture supplies the contrast; picture_covers_title owns that case
        findings.append(
            _finding(
                "title_illegible",
                slide_index,
                str(layout.get("key")),
                index,
                f"title slot idx{index} is set to {slot.get('font_color')} and layout "
                f"{layout.get('key')!r} paints no backdrop behind it — the title is "
                "invisible on the plain background",
            )
        )
    return findings


def check_empty_content_next_to_picture(
    slide_index: int,
    layout: dict[str, Any],
    texts: dict[int, list[str]],
    pictures: dict[int | None, Any],
) -> list[dict[str, Any]]:
    """Information, not a defect: half the slide reads as unfinished."""
    if not pictures:
        return []
    if not any(texts.get(int(slot.get("idx") or 0)) for slot in slots_by_role(layout, "title")):
        return []
    empty = sorted(
        int(slot.get("idx") or 0)
        for slot in slots_by_role(layout, "content")
        if not texts.get(int(slot.get("idx") or 0))
    )
    if not empty:
        return []
    return [
        _finding(
            "empty_content_next_to_picture",
            slide_index,
            str(layout.get("key")),
            empty[0],
            f"content slot(s) {empty} stayed empty next to a picture — that area of "
            "the slide reads as unfinished; add bullets or choose a picture-only layout",
            severity="info",
        )
    ]

def check_image_distortion(
    slide_index: int, layout: dict[str, Any], pictures: dict[int | None, Any]
) -> list[dict[str, Any]]:
    key = str(layout.get("key"))
    findings: list[dict[str, Any]] = []
    for index, picture in _picture_items(pictures):
        try:
            native_w, native_h = picture.image.size
            crop_w = 1.0 - float(picture.crop_left) - float(picture.crop_right)
            crop_h = 1.0 - float(picture.crop_top) - float(picture.crop_bottom)
            rendered = float(picture.width) / float(picture.height)
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            continue
        source_w = native_w * crop_w
        source_h = native_h * crop_h
        if source_w <= 0 or source_h <= 0:
            continue
        source = source_w / source_h
        deviation = abs(rendered - source) / source
        if deviation <= _ASPECT_TOLERANCE:
            continue
        findings.append(
            _finding(
                "image_distorted", slide_index, key, index,
                f"picture at slot idx{index} renders at aspect {rendered:.3f} but its "
                f"(cropped) source aspect is {source:.3f} — {deviation * 100:.1f}% distortion",
            )
        )
    return findings


__all__ = [
    "check_empty_content_next_to_picture",
    "check_image_distortion",
    "check_picture_covers_title",
    "check_title_illegible",
]
