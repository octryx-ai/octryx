"""Use learned layout usage to choose among equally capable layouts.

Usage records come from ``layout_usage``; this module only reads them. A
layout without usage evidence is never ranked by usage.
"""

from __future__ import annotations

from typing import Any

#: One line of difference weighs as much as this many characters. A layout used
#: for three-line bullet lists is a worse home for a fifteen-line list than one
#: whose samples run long, even when the character counts happen to be close.
_LINE_WEIGHT = 30


def usage_text_volume(usage: dict[str, Any] | None) -> tuple[int, int] | None:
    """Typical (lines, characters) this layout's text slots carry, summed.

    Title slots are included: a layout's title length is part of how it is used.
    ``None`` when the layout has no usage evidence at all.
    """
    if not isinstance(usage, dict):
        return None
    slots = usage.get("slots")
    if not isinstance(slots, (list, tuple)) or not slots:
        return None
    lines = 0
    chars = 0
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        lines += int((slot.get("lines") or {}).get("median") or 0)
        chars += int((slot.get("chars") or {}).get("median") or 0)
    return lines, chars


def pick_layout_by_usage(
    layouts: list[dict[str, Any]], *, lines: int, chars: int
) -> dict[str, Any] | None:
    """Among equally capable layouts, the one whose learned usage fits best.

    Layouts the template author actually used come first — a demonstrated
    layout is better evidence than an unused one of the same shape. Within
    those, the smaller distance to the learned text volume wins. Ties fall back
    to the template's own layout order, exactly like the composer's ranking, so
    the choice stays deterministic.

    Returns ``None`` when *no* candidate carries usage evidence. Usage decides
    only where usage exists; a template without sample slides keeps the
    composer's capacity ranking untouched.
    """
    scored = [
        (layout, volume)
        for layout in layouts
        for volume in (usage_text_volume(layout.get("usage")),)
        if volume is not None
    ]
    if not scored:
        return None

    def rank(item: tuple[dict[str, Any], tuple[int, int]]) -> tuple[int, int, str]:
        layout, (used_lines, used_chars) = item
        distance = abs(chars - used_chars) + _LINE_WEIGHT * abs(lines - used_lines)
        return (distance, int(layout.get("order") or 0), str(layout.get("key") or ""))

    return min(scored, key=rank)[0]


__all__ = ["pick_layout_by_usage", "usage_text_volume"]
