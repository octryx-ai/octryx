"""The "when to use which layout" table of the corporate identity guide."""

from __future__ import annotations

from typing import Any

#: (goal, content_shape prefixes that serve it), in reading order.
_GOALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Opening title slide", ("title_slide",)),
    ("Chapter divider", ("section",)),
    ("Bullets / text", ("bullets",)),
    ("Two-column comparison", ("two_content", "columns_2")),
    ("Visual topics with icons", ("icons_",)),
    ("Topics in columns", ("columns_3", "columns_4")),
    ("Bold key message", ("statement",)),
    ("Pull quote", ("quote",)),
    ("Agenda / TOC", ("agenda",)),
    ("Image with text", ("content_with_picture",)),
    ("Freeform custom", ("blank", "title_only")),
    ("Closing slide", ("section",)),
)


def layout_choice_lines(safe_layouts: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for goal, prefixes in _GOALS:
        names = [
            str(layout.get("name") or "")
            for layout in safe_layouts
            if str(layout.get("content_shape") or "").startswith(prefixes) and layout.get("name")
        ]
        if names:
            rows.append(f"| {goal} | {' or '.join(f'`{name}`' for name in names[:3])} |")
    if not rows:
        return []
    return ["## When to Use Which Layout", "| Goal | Use Layout |", "|------|-----------|", *rows, ""]


def first_layout(layouts: list[dict[str, Any]], *prefixes: str) -> dict[str, Any] | None:
    for prefix in prefixes:
        for layout in layouts:
            if str(layout.get("content_shape") or "").startswith(prefix):
                return layout
    return None


__all__ = ["first_layout", "layout_choice_lines"]
