"""Which layout shape can hold a planned slide — capacity only, never names."""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import SlideDraft, mapping, text
from .aws_deck_sections import divider_layout_key
from .layout_usage_fit import pick_layout_by_usage
from .picture_safe_area import title_is_legible


def _can_hold(layout: dict[str, Any], units: int, pictures: int, title: bool, subtitle: bool) -> bool:
    capacity = mapping(layout.get("capacity"))
    if units > int(capacity.get("content_units") or 0):
        return False
    if pictures > int(capacity.get("picture_slots") or 0):
        return False
    if title and not int(capacity.get("title_slots") or 0):
        return False
    if subtitle and not int(capacity.get("subtitle_slots") or 0):
        return False
    return True


def _fitting_layouts(
    template_snapshot: dict[str, Any], units: int, pictures: int, title: bool, subtitle: bool
) -> list[dict[str, Any]]:
    layouts = template_snapshot.get("layouts")
    if not isinstance(layouts, (list, tuple)):
        return []
    fitting = [
        layout
        for layout in layouts
        if isinstance(layout, dict) and _can_hold(layout, units, pictures, title, subtitle)
    ]
    if not title:
        return fitting
    # A layout whose title is a light colour with nothing painted behind it
    # renders a titled slide with no visible heading — the gate calls that
    # ``title_illegible``. The planner prefers fitting layouts with readable headings.
    # Preference, not exclusion: a template offering nothing else keeps working
    # and the gate still reports the fact.
    legible = [layout for layout in fitting if title_is_legible(layout)]
    return legible or fitting


def _pick_shape(
    template_snapshot: dict[str, Any],
    preference: tuple[str, ...],
    units: int,
    pictures: int,
    title: bool,
    subtitle: bool,
) -> str:
    fitting = _fitting_layouts(template_snapshot, units, pictures, title, subtitle)
    if preference[:1] == ("title_slide",):
        exact_titles = {text(layout.get("content_shape")) for layout in fitting
                        if int(mapping(layout.get("capacity")).get("content_units") or 0) == units}
        for shape in ("title_slide", "title_and_subtitle"):
            if shape in preference and shape in exact_titles:
                return shape
        if any(text(layout.get("content_shape")) == "title_slide" for layout in fitting):
            return "title_slide"
    exact = {
        text(layout.get("content_shape"))
        for layout in fitting
        if int(mapping(layout.get("capacity")).get("content_units") or 0) == units
    }
    available = {text(layout.get("content_shape")) for layout in fitting}
    for candidates in (exact, available):
        for shape in preference:
            if shape in candidates:
                return shape
    return ""


def _text_volume(draft: SlideDraft) -> tuple[int, int]:
    pieces = [draft.title, draft.subtitle]
    pieces.extend(block.heading for block in draft.blocks)
    pieces.extend(bullet.text for bullet in draft.all_bullets())
    pieces = [piece for piece in pieces if piece]
    return len(pieces), sum(len(piece) for piece in pieces)


def _pick_layout_key(
    template_snapshot: dict[str, Any], draft: SlideDraft, shape: str
) -> str:
    if not shape or draft.images:
        return ""
    if shape == "section":
        divider = divider_layout_key(template_snapshot)
        if divider:
            return divider
    units = draft.content_units()
    candidates = [
        layout
        for layout in _fitting_layouts(
            template_snapshot, units, 0, bool(draft.title), bool(draft.subtitle)
        )
        if text(layout.get("content_shape")) == shape
    ]
    if len(candidates) < 2:
        return ""
    lines, chars = _text_volume(draft)
    chosen = pick_layout_by_usage(candidates, lines=lines, chars=chars)
    return text(chosen.get("key")) if chosen else ""


def place_title_date(
    draft: SlideDraft, template_snapshot: dict[str, Any], shapes: tuple[str, ...]
) -> None:
    dated = [bullet for bullet in draft.bullets if bullet.key == "as_of"]
    if not dated:
        return
    units = draft.content_units()
    if _pick_shape(template_snapshot, shapes, units, 0, True, bool(draft.subtitle)):
        return
    line = dated[0]
    draft.bullets = [bullet for bullet in draft.bullets if bullet is not line]
    sources = [draft.subtitle_source or draft.source] if draft.subtitle else []
    draft.subtitle = f"{draft.subtitle} · {line.text}" if draft.subtitle else line.text
    draft.subtitle_source = "; ".join([*sources, line.source])


__all__ = [
    "_can_hold",
    "_fitting_layouts",
    "_pick_layout_key",
    "_pick_shape",
    "_text_volume",
    "place_title_date",
]
