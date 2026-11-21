"""The "when to use which layout" table of the corporate identity guide.

Built from the template's own layouts: each goal lists the corporate-safe
layouts whose structural ``content_shape`` serves it, by the names this
template gives them. A goal the template has no layout for is left out — the
guide never names a layout the template does not ship.
"""

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
    """Markdown table: goal -> the template's own layout names for it."""
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
    """The first layout (template order) whose ``content_shape`` starts with a prefix."""
    for prefix in prefixes:
        for layout in layouts:
            if str(layout.get("content_shape") or "").startswith(prefix):
                return layout
    return None


__all__ = ["first_layout", "layout_choice_lines"]
