"""Deterministic classification of a layout's placeholder set.

The layout catalog is only useful for composition if every layout states what
it can *hold*. Classification is structural first, in this order:

1. the placeholder roles, their counts and their geometry (column pairs become
   ``columns_N``; a full-size picture ``picture_full``; …);
2. the editor-written layout type (``sldLayout@type``: ``secHead`` is a
   section, ``title`` a title slide) — language independent, unlike names;
3. the layout's static icon holders: ``columns_N`` with one holder per column
   is ``icons_N``.

Only where structure leaves a tie does the layout name act as a hint, from an
explicit closed vocabulary, and only towards a shape the structure supports
(a "table of content" name turns a bullets layout into ``agenda``; a name never turns
a text layout into a picture layout). Nothing here scores or guesses: an
unrecognised name, or a template whose names are "Layout 1…n", simply keeps
the structural shape.
"""

from __future__ import annotations

from typing import Any

TITLE_TYPES = frozenset({"title", "ctrTitle"})
SUBTITLE_TYPES = frozenset({"subTitle"})
CONTENT_TYPES = frozenset({"body", "obj", "tbl", "chart", "dgm"})
PICTURE_TYPES = frozenset({"pic", "clipArt"})
MEDIA_TYPES = frozenset({"media"})
CHROME_TYPES = frozenset({"ftr", "sldNum", "dt", "hdr"})

#: Column x-offsets within this many EMU count as the same column (~0.5 mm).
_COLUMN_TOLERANCE_EMU = 20_000

#: A single picture covering at least this fraction of the slide is "full".
_FULL_PICTURE_AREA_RATIO = 0.5

#: Explicit name tokens, checked in order — tie-breaking hints only. Each maps
#: to a vocabulary entry that is applied only when the structure supports it.
_NAME_VOCABULARY: tuple[tuple[str, str], ...] = (
    ("diagram", "diagram"),
    ("icon", "icons"),
    ("quote", "quote"),
    ("contact", "contact"),
    ("statement", "statement"),
    ("section", "section"),
    ("table of content", "agenda"),
    ("agenda", "agenda"),
)


def slot_role(placeholder_type: str) -> str:
    if placeholder_type in TITLE_TYPES:
        return "title"
    if placeholder_type in SUBTITLE_TYPES:
        return "subtitle"
    if placeholder_type in PICTURE_TYPES:
        return "picture"
    if placeholder_type in MEDIA_TYPES:
        return "media"
    if placeholder_type in CHROME_TYPES:
        return "chrome"
    if placeholder_type in CONTENT_TYPES:
        return "content"
    return "content"


def _by_role(slots: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [slot for slot in slots if slot.get("role") == role]


def _paired_column_count(content_slots: list[dict[str, Any]]) -> int:
    """Count heading/body column pairs (the heading-over-body topic columns structure).

    Requires every content slot to carry geometry and to fall into columns of
    exactly two slots each; anything else returns 0.
    """
    if len(content_slots) < 4 or len(content_slots) % 2:
        return 0
    columns: list[tuple[int, int]] = []  # (x_emu, count)
    for slot in sorted(content_slots, key=lambda item: item.get("x_emu") or 0):
        x_emu = slot.get("x_emu")
        if not isinstance(x_emu, int) or slot.get("w_emu") is None:
            return 0
        if columns and abs(x_emu - columns[-1][0]) <= _COLUMN_TOLERANCE_EMU:
            columns[-1] = (columns[-1][0], columns[-1][1] + 1)
        else:
            columns.append((x_emu, 1))
    if len(columns) < 2:
        return 0
    if any(count != 2 for _, count in columns):
        return 0
    return len(columns)


def _picture_is_full(picture_slots: list[dict[str, Any]], slide_size: dict[str, int]) -> bool:
    slide_area = int(slide_size.get("width_emu") or 0) * int(slide_size.get("height_emu") or 0)
    if slide_area <= 0:
        return False
    for slot in picture_slots:
        width = slot.get("w_emu")
        height = slot.get("h_emu")
        if isinstance(width, int) and isinstance(height, int):
            if (width * height) / slide_area >= _FULL_PICTURE_AREA_RATIO:
                return True
    return False


def _structural_shape(
    counts: dict[str, int],
    pairs: int,
    has_center_title: bool,
    picture_is_full: bool,
) -> str:
    if not any(counts[role] for role in ("title", "subtitle", "content", "picture", "media")):
        return "blank"
    if counts["media"]:
        return "media_full"
    if counts["picture"] >= 3:
        return f"image_grid_{counts['picture']}"
    if pairs >= 2:
        return f"columns_{pairs}"
    if counts["picture"] >= 1 and counts["content"] == 0:
        return "picture_full" if picture_is_full else "picture"
    if counts["picture"] >= 1:
        return "content_with_picture"
    if has_center_title and counts["content"] <= 1:
        return "title_slide"
    if counts["content"] >= 3:
        return f"content_{counts['content']}"
    if counts["content"] == 2:
        return "two_content"
    if counts["content"] == 1:
        return "bullets"
    if counts["subtitle"]:
        return "title_and_subtitle"
    if counts["title"]:
        return "title_only"
    return "blank"


#: Structures a title-and-subtitle style hint (section, statement, quote) may
#: refine: a title with at most a subtitle and nothing else.
_TITLE_STRUCTURES = frozenset({"title_slide", "title_and_subtitle", "title_only"})


def _hinted_shape(structural: str, name: str, counts: dict[str, int], units: int) -> str:
    """Apply the first name hint the structure supports; otherwise keep it."""
    lowered = name.lower()
    for token, vocabulary in _NAME_VOCABULARY:
        if token not in lowered:
            continue
        if vocabulary == "diagram" and structural in {"picture", "picture_full"}:
            return "diagram_full"
        if vocabulary == "icons" and structural.startswith("columns_"):
            return f"icons_{units}"
        if vocabulary == "contact" and (counts["picture"] or counts["content"]):
            return f"contact_{counts['picture'] or units or 1}"
        if vocabulary in {"quote", "statement", "section"} and structural in _TITLE_STRUCTURES:
            return vocabulary
        if vocabulary == "agenda" and structural == "bullets":
            return "agenda"
        return structural
    return structural


def _typed_shape(structural: str, layout_type: str) -> str:
    """The shape the editor-written layout type states, or ``""``."""
    if layout_type == "secHead" and structural in _TITLE_STRUCTURES:
        return "section"
    if layout_type == "title" and structural in {"title_and_subtitle", "title_only"}:
        return "title_slide"
    return ""


def promote_section_caption(slots: list[dict[str, Any]], layout_type: str) -> None:
    """A section layout's single text body is its subtitle line, not content.

    Editors give section headers one ``body`` placeholder under the title for a
    short description. Counted as content it would make the divider a bullets
    layout whose body every divider leaves empty; as a subtitle it is the
    optional second line it is drawn as. Only ``body`` (text) placeholders are
    promoted — an ``obj`` slot can hold anything and stays content.
    """
    if layout_type != "secHead":
        return
    bodies = [slot for slot in slots if slot.get("role") == "content"]
    if len(bodies) == 1 and bodies[0].get("placeholder_type") == "body" and not _by_role(slots, "subtitle"):
        bodies[0]["role"] = "subtitle"


def classify_layout(
    name: str,
    slots: list[dict[str, Any]],
    slide_size: dict[str, int],
    *,
    layout_type: str = "",
    icon_holders: int = 0,
) -> tuple[str, dict[str, int]]:
    """Return ``(content_shape, capacity)`` for a layout's slot set.

    ``layout_type`` is ``sldLayout@type`` (empty when the template omits it) and
    ``icon_holders`` the number of static icon holders the layout draws.
    """
    promote_section_caption(slots, layout_type)
    counts = {
        role: len(_by_role(slots, role))
        for role in ("title", "subtitle", "content", "picture", "media", "chrome")
    }
    content_slots = _by_role(slots, "content")
    picture_slots = _by_role(slots, "picture")
    pairs = _paired_column_count(content_slots)
    has_center_title = any(slot.get("placeholder_type") == "ctrTitle" for slot in slots)

    structural = _structural_shape(
        counts, pairs, has_center_title, _picture_is_full(picture_slots, slide_size)
    )
    units = pairs if pairs >= 2 else counts["content"]
    if structural.startswith("columns_") and icon_holders == pairs:
        shape = f"icons_{pairs}"
    else:
        shape = _typed_shape(structural, layout_type) or _hinted_shape(structural, name, counts, units)

    capacity = {
        "content_units": units,
        "body_slots": counts["content"],
        "picture_slots": counts["picture"],
        "title_slots": counts["title"],
        "subtitle_slots": counts["subtitle"],
        "paired_columns": pairs,
    }
    return shape, capacity


#: content_shape prefix -> layout category (title, section, icons, …).
_CATEGORY_BY_SHAPE: tuple[tuple[str, str], ...] = (
    ("title_slide", "title"),
    ("section", "section"),
    ("icons_", "icons"),
    ("statement", "statement"),
    ("quote", "statement"),
    ("contact_", "contact"),
    ("picture", "picture"),
    ("content_with_picture", "picture"),
    ("image_grid_", "picture"),
    ("diagram_full", "picture"),
    ("media_full", "picture"),
    ("blank", "blank"),
)


def category_for_shape(content_shape: str) -> str:
    """The coarse layout category a ``content_shape`` belongs to."""
    for prefix, category in _CATEGORY_BY_SHAPE:
        if content_shape.startswith(prefix):
            return category
    return "content"


__all__ = [
    "CHROME_TYPES",
    "CONTENT_TYPES",
    "MEDIA_TYPES",
    "PICTURE_TYPES",
    "SUBTITLE_TYPES",
    "TITLE_TYPES",
    "category_for_shape",
    "classify_layout",
    "promote_section_caption",
    "slot_role",
]
