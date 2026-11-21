"""Which layout shapes a template lacks, and how a derivative layout would close the gap.

The composer needs a layout that shows a large diagram next to a visible
title. This module decides whether the template already has one and, if not,
which of its own layouts to clone and where the picture placeholder goes: the
content band between the donor's title, the template's footer row and the
gutter its own layouts start their content at.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .layout_authoring import LayoutSpec
from .template_snapshot import slots_by_role

#: A picture area smaller than half the slide is an illustration, not a
#: diagram: an AWS topology rendered into it stops being readable. The value is
#: the dividing line between "the template already has a diagram layout" and
#: "the gap is real", and it is applied to both the gap check and the donor.
DIAGRAM_MIN_AREA_RATIO = 0.5

DIAGRAM_FULL_SHAPE = "diagram_full"
DIAGRAM_FULL_NAME = "Diagram Full (generated)"


def _slide_area(snapshot: dict[str, Any]) -> int:
    size = snapshot.get("slide_size") or {}
    return int(size.get("width_emu") or 0) * int(size.get("height_emu") or 0)


def find_diagram_full_layout(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """A layout that already satisfies ``diagram_full``, or ``None``.

    The three conditions are exactly what the shape means: the slide keeps a
    title, the picture area is large, and the picture does not cover the brand
    (``full_bleed`` is the snapshot's own verdict on that, computed from area
    and from which chrome slots the picture swallows).
    """
    for layout in snapshot.get("layouts", []):
        if not slots_by_role(layout, "title"):
            continue
        for slot in slots_by_role(layout, "picture"):
            if slot.get("full_bleed"):
                continue
            ratio = slot.get("slide_area_ratio")
            if isinstance(ratio, (int, float)) and float(ratio) >= DIAGRAM_MIN_AREA_RATIO:
                return layout
    return None


def template_chrome_top_emu(layouts: list[dict[str, Any]]) -> int | None:
    """The top edge of the template's footer row, or ``None`` if it has none.

    Layouts that declare no chrome placeholder of their own still print the
    master's footer and logo, so the row cannot be read from one layout alone.
    Each layout that *does* declare chrome contributes its highest chrome edge,
    and the most common of those values is the template's row (ties resolve to
    the smaller value, so the result is deterministic) — the same rule
    ``template_margin_emu`` uses for the gutter.
    """
    per_layout: Counter[int] = Counter()
    for layout in layouts:
        tops = [
            slot["y_emu"]
            for slot in layout.get("chrome_slots", ())
            if isinstance(slot, dict) and isinstance(slot.get("y_emu"), int) and slot["y_emu"] > 0
        ]
        if tops:
            per_layout[min(tops)] += 1
    if not per_layout:
        return None
    best = max(per_layout.values())
    return min(value for value, count in per_layout.items() if count == best)


def content_band(
    snapshot: dict[str, Any],
    layout: dict[str, Any],
    margin_emu: int,
    chrome_top_emu: int | None,
) -> dict[str, int] | None:
    """The slide band between this layout's title and the template's footer row.

    Derived directly from the template geometry: the title slot's bottom
    edge, the footer row's top edge, and the gutter the template's own layouts
    start their content at. Nothing is guessed — a template without any of the
    three simply yields a smaller band, and a layout whose title leaves no room
    yields ``None`` and is passed over as a donor.

    Unlike the run-time inset in ``picture_safe_area``, no width threshold
    applies here: that threshold protects against cutting a slot down over a
    narrow box, whereas this band is being authored full width, so *every*
    protected placeholder has to be cleared. python-pptx's own default template
    proved the difference — its caption title is too narrow to count as a band,
    and reusing the run-time rule produced a layout whose picture covered the
    title.
    """
    size = snapshot.get("slide_size") or {}
    width = int(size.get("width_emu") or 0)
    height = int(size.get("height_emu") or 0)
    if width <= 0 or height <= 0:
        return None
    left, right = margin_emu, width - margin_emu
    top, bottom = margin_emu, height - margin_emu
    if chrome_top_emu is not None:
        bottom = min(bottom, chrome_top_emu - margin_emu)
    protected = [
        slot
        for slot in [*slots_by_role(layout, "title"), *(layout.get("chrome_slots") or ())]
        if isinstance(slot, dict)
    ]
    for slot in protected:
        y_emu, h_emu = slot.get("y_emu"), slot.get("h_emu")
        if not isinstance(y_emu, int) or not isinstance(h_emu, int) or h_emu <= 0:
            continue
        if y_emu + h_emu / 2 < height / 2:
            top = max(top, y_emu + h_emu + margin_emu)
        else:
            bottom = min(bottom, y_emu - margin_emu)
    if right <= left or bottom <= top:
        return None
    return {"x_emu": left, "y_emu": top, "w_emu": right - left, "h_emu": bottom - top}


def _title_is_styled_for_the_plain_background(layout: dict[str, Any]) -> bool:
    """Whether this layout's title is written to be read without a picture.

    A layout whose picture slot is full bleed styles its title *for the photo*:
    a donor layout may write its title run as ``bg1`` — light — because a dark
    band and a photograph always sit behind it. Clone that layout, inset the
    picture and the title becomes white on the white master background, i.e.
    invisible. So the criterion is structural rather than a fill probe: only a
    layout that never puts a picture behind its title can be trusted to have
    styled that title for the plain slide.
    """
    return not any(slot.get("full_bleed") for slot in slots_by_role(layout, "picture"))


def _diagram_donor(
    snapshot: dict[str, Any], margin_emu: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]] | None:
    """Pick the layout to clone for the diagram layout.

    Requirements: a title, a picture placeholder to move, and a title that
    stays legible once the picture is no longer behind it. The picture
    placeholder is then given the layout's content band — so the donor
    contributes its identity and its title styling, and the geometry comes from
    the template's own title/chrome/gutter measurements.

    Ranking: the largest existing picture slot first (that layout already leans
    visual, so the fewest of its other placeholders are lost), then the
    template's own master and layout order as the author's evidence.
    """
    slide_area = _slide_area(snapshot)
    if slide_area <= 0:
        return None
    chrome_top = template_chrome_top_emu(snapshot.get("layouts", []))
    best_key: tuple[int, int, int, int] | None = None
    best: tuple[dict[str, Any], dict[str, Any], dict[str, int]] | None = None
    for layout in snapshot.get("layouts", []):
        if not slots_by_role(layout, "title"):
            continue
        if not _title_is_styled_for_the_plain_background(layout):
            continue
        band = content_band(snapshot, layout, margin_emu, chrome_top)
        if band is None or (band["w_emu"] * band["h_emu"]) / slide_area < DIAGRAM_MIN_AREA_RATIO:
            continue
        for slot in slots_by_role(layout, "picture"):
            area = int(slot.get("w_emu") or 0) * int(slot.get("h_emu") or 0)
            if area <= 0:
                continue
            key = (
                -area,
                int(layout.get("master_index") or 0),
                int(layout.get("order") or 0),
                int(slot.get("idx") or 0),
            )
            if best_key is None or key < best_key:
                best_key, best = key, (layout, slot, band)
    return best


def _diagram_spec(snapshot: dict[str, Any], margin_emu: int) -> LayoutSpec | None:
    donor = _diagram_donor(snapshot, margin_emu)
    if donor is None:
        return None
    layout, slot, rect = donor
    ratio = round((rect["w_emu"] * rect["h_emu"]) / _slide_area(snapshot), 4)
    return LayoutSpec(
        name=DIAGRAM_FULL_NAME,
        shape=DIAGRAM_FULL_SHAPE,
        donor_part=str(layout.get("part")),
        master_part=str(layout.get("master_part")),
        picture_idx=int(slot.get("idx") or 0),
        picture_rect=rect,
        rationale=(
            f"cloned from {layout.get('key')!r}, whose title is styled for the plain "
            f"slide background (no full-bleed picture behind it); its picture "
            f"placeholder idx {slot.get('idx')} grew from {slot.get('slide_area_ratio')} "
            f"to {ratio} of the slide by taking the content band between the title "
            f"slot's bottom edge and the chrome row, at the template gutter of "
            f"{margin_emu} EMU — title, logo and footer stay visible"
        ),
        extra_marker={"donorKey": str(layout.get("key") or "")},
    )


def analyse_gaps(snapshot: dict[str, Any], margin_emu: int) -> dict[str, Any]:
    """Which required shapes the template covers, and what would close a gap."""
    existing = find_diagram_full_layout(snapshot)
    spec = None if existing is not None else _diagram_spec(snapshot, margin_emu)
    return {
        "required_shapes": [DIAGRAM_FULL_SHAPE],
        "covered": {
            DIAGRAM_FULL_SHAPE: str(existing.get("key")) if existing is not None else None
        },
        "specs": [spec] if spec is not None else [],
        "unsatisfiable": (
            [DIAGRAM_FULL_SHAPE] if existing is None and spec is None else []
        ),
    }


__all__ = [
    "DIAGRAM_FULL_NAME",
    "DIAGRAM_FULL_SHAPE",
    "DIAGRAM_MIN_AREA_RATIO",
    "analyse_gaps",
    "content_band",
    "find_diagram_full_layout",
    "template_chrome_top_emu",
]
