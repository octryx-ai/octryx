"""Which layout shape can hold a planned slide — capacity only, never names.

Shared by the AWS and the generic deck planners: a slide draft states how many
content units, pictures, titles and subtitles it needs, and these helpers pick
the first preferred ``content_shape`` some layout of the template can really
carry, then the layout of that shape whose demonstrated usage fits best.
"""

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
    """First preferred shape whose layouts can really hold the slide.

    An exact capacity match wins over a merely sufficient one: a layout with a
    body slot this slide has nothing sourced for would leave that slot empty,
    which the slide gate rightly reports as ``empty_required_slot``. The planner
    does not fill it with prose to make the layout look used — it picks the
    layout the evidence actually fills.

    The cover (``title_slide`` preferred first) never falls to a divider while
    a title layout can hold it: exact title layouts first, then a title layout
    whose optional strapline stays empty, and only then the rest. Many title
    layouts carry such a third line; exactness alone would put the cover on a
    section header in a template without a plain title-and-subtitle layout.
    """
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
    """(lines, characters) this slide will put into the template's text slots."""
    pieces = [draft.title, draft.subtitle]
    pieces.extend(block.heading for block in draft.blocks)
    pieces.extend(bullet.text for bullet in draft.all_bullets())
    pieces = [piece for piece in pieces if piece]
    return len(pieces), sum(len(piece) for piece in pieces)


def _pick_layout_key(
    template_snapshot: dict[str, Any], draft: SlideDraft, shape: str
) -> str:
    """The layout of this shape whose *demonstrated* usage fits the content.

    The template's own sample slides record how much text each layout normally
    carries; among several layouts of the same shape the closest match wins.

    Deliberately skipped for slides carrying a picture: naming a ``layout_key``
    bypasses the composer's full-bleed protection, and no amount of usage
    evidence is worth losing the logo over. Those slides keep the composer's
    capacity ranking.
    """
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
    """Keep the title slide on a title layout, wherever its date line has to go.

    The date travels as the draft's one body line. A title layout that offers a
    third text slot (a strapline under title and subtitle) carries it there.
    Most templates — the editor defaults among them — offer title and subtitle
    only; a third line would push the slide onto a title-and-content layout and
    turn its subtitle into a marker. There the date joins the subtitle line
    instead, and its source is kept in the notes.
    """
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
