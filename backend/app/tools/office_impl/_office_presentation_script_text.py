"""Text and normalization helpers for generated presentation scripts."""

from __future__ import annotations

from typing import Any

from ._office_presentation_normalization import _normalize_slide_spec

PRESENTATION_SOURCE_INDEX: dict[str, int] = {
    "title": 1,
    "agenda": 3,
    "section": 71,
    "quote": 72,
    "two_columns": 84,
    "three_columns": 85,
    "four_columns": 86,
    "bullets": 3,
    "table": 3,
    "chart": 3,
    "process_flow": 3,
}


def escape_presentation_py_str(text: str) -> str:
    """Escape a string for embedding inside a Python triple-quoted string."""
    return text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def quality_checked_presentation_slides(
    slides: list[dict[str, Any]],
    *,
    aggressive: bool = False,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_slide in slides:
        if not isinstance(raw_slide, dict):
            continue
        fitted = _normalize_slide_spec(raw_slide, aggressive=aggressive)
        if fitted:
            normalized.append(fitted)
    return normalized


def _set_text_line(sp: str, shape: int, text: str, size: str = "") -> str:
    """One ``set_text`` call of the generated script; the text sits in a triple-quoted string."""
    size_arg = f', size="{size}"' if size else ""
    return f'    set_text(ops, "{sp}/shape[{shape}]", """{escape_presentation_py_str(text)}"""{size_arg})'


def _field(slide: dict[str, Any], key: str) -> str:
    return str(slide.get(key) or "").strip()


def _title_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    title, subtitle, footer = _field(slide, "title"), _field(slide, "subtitle"), _field(slide, "footer")
    if title:
        lines.append(_set_text_line(sp, 1, title))
    if subtitle:
        lines.append(_set_text_line(sp, 2, subtitle, "16pt"))
    if footer:
        lines.append(_set_text_line(sp, 3, footer, "12pt"))
    return lines


def _agenda_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    title, subtitle, items = _field(slide, "title"), _field(slide, "subtitle"), slide.get("items")
    if title:
        lines.append(_set_text_line(sp, 4, title))
    if subtitle:
        lines.append(_set_text_line(sp, 3, subtitle, "16pt"))
    if isinstance(items, list) and items:
        lines.append(_set_text_line(sp, 1, "\n".join(str(i) for i in items)))
    return lines


def _section_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    title, subtitle = _field(slide, "title"), _field(slide, "subtitle")
    if title:
        lines.append(_set_text_line(sp, 3, title))
    if subtitle:
        lines.append(_set_text_line(sp, 2, subtitle))
    return lines


def _quote_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    slide_title, quote, author = _field(slide, "title"), _field(slide, "quote"), _field(slide, "author")
    if slide_title:
        lines.append(_set_text_line(sp, 2, slide_title))
    if quote:
        lines.append(_set_text_line(sp, 3, quote))
    if author:
        lines.append(_set_text_line(sp, 4, author, "16pt"))
    return lines


def _bullets_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    title, bullets = _field(slide, "title"), slide.get("bullets")
    subtitle, body = _field(slide, "subtitle"), _field(slide, "body")
    if title:
        lines.append(_set_text_line(sp, 4, title))
    if subtitle:
        lines.append(_set_text_line(sp, 3, subtitle, "16pt"))
    if isinstance(bullets, list) and bullets:
        lines.append(_set_text_line(sp, 1, "\n".join(str(b) for b in bullets)))
    elif body:
        lines.append(_set_text_line(sp, 1, body))
    return lines


def _visual_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    """Table, chart and process flow slides: title texts, the body placeholder is emptied for the visual."""
    lines: list[str] = []
    title, subtitle = _field(slide, "title"), _field(slide, "subtitle")
    if title:
        lines.append(_set_text_line(sp, 4, title))
    if subtitle:
        lines.append(_set_text_line(sp, 3, subtitle, "16pt"))
    lines.append(f'    set_text(ops, "{sp}/shape[1]", "")')
    return lines


# Per column layout: the title shape and the (label shape, body shape) of each column in the template slide.
_COLUMN_SHAPES: dict[str, tuple[int, list[tuple[int, int]]]] = {
    "two_columns": (3, [(7, 5), (8, 6)]),
    "three_columns": (6, [(9, 8), (12, 11), (14, 13)]),
    "four_columns": (2, [(5, 4), (8, 7), (11, 10), (14, 13)]),
}


def _columns_slide_ops(slide: dict[str, Any], sp: str) -> list[str]:
    lines: list[str] = []
    title_shape, column_shapes = _COLUMN_SHAPES[str(slide.get("layout_type") or "").strip()]
    title = _field(slide, "title")
    columns = slide.get("columns") or []
    if title:
        lines.append(_set_text_line(sp, title_shape, title))
    for i, (label_shape, body_shape) in enumerate(column_shapes):
        if i < len(columns) and isinstance(columns[i], dict):
            label, body = _field(columns[i], "label"), _field(columns[i], "body")
            if label:
                lines.append(_set_text_line(sp, label_shape, label, "16pt"))
            if body:
                lines.append(_set_text_line(sp, body_shape, body))
    return lines


_SLIDE_TEXT_OPS = {
    "title": _title_slide_ops,
    "agenda": _agenda_slide_ops,
    "section": _section_slide_ops,
    "quote": _quote_slide_ops,
    "bullets": _bullets_slide_ops,
    "table": _visual_slide_ops,
    "chart": _visual_slide_ops,
    "process_flow": _visual_slide_ops,
    "two_columns": _columns_slide_ops,
    "three_columns": _columns_slide_ops,
    "four_columns": _columns_slide_ops,
}


def build_presentation_text_ops_code(slides: list[dict[str, Any]]) -> str:
    """Generate the body of build_text_ops() for the given slides."""
    lines: list[str] = ["    ops: list[dict] = []", ""]
    for idx, slide in enumerate(slides, start=1):
        layout = str(slide.get("layout_type") or "").strip()
        lines.append(f"    # Slide {idx} ({layout})")
        slide_ops = _SLIDE_TEXT_OPS.get(layout)
        if slide_ops is not None:
            lines.extend(slide_ops(slide, f"/slide[{idx}]"))
        lines.append("")

    lines.append("    return ops")
    return "\n".join(lines)


__all__ = [
    "PRESENTATION_SOURCE_INDEX",
    "build_presentation_text_ops_code",
    "escape_presentation_py_str",
    "quality_checked_presentation_slides",
]
