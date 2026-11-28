"""Use learned layout usage to choose among equally capable layouts."""

from __future__ import annotations

from typing import Any

#: One line of difference weighs as much as this many characters. A layout used
#: for three-line bullet lists is a worse home for a fifteen-line list than one
#: whose samples run long, even when the character counts happen to be close.
_LINE_WEIGHT = 30


def usage_text_volume(usage: dict[str, Any] | None) -> tuple[int, int] | None:
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
