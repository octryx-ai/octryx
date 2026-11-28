"""Slide payload normalization helpers for presentation script tools."""

from __future__ import annotations

from typing import Any

from ._office_presentation_payloads import (
    _normalize_chart_payload,
    _normalize_column_payload,
    _normalize_diagram_steps,
    _normalize_table_payload,
)
from ._office_presentation_text import _compact_bullet_lines, _truncate_presentation_text

_ROLE_LAYOUTS = {
    "title": "title",
    "title_cover": "title",
    "closing_takeaway": "title",
    "agenda": "agenda",
    "section": "section",
    "overview_hero": "section",
    "quote": "quote",
    "bullets": "bullets",
    "operations_content": "bullets",
    "two_columns": "two_columns",
    "three_columns": "three_columns",
    "four_columns": "four_columns",
    "table": "table",
    "chart": "chart",
    "comparison_chart": "chart",
    "diagram": "process_flow",
    "workflow": "process_flow",
    "process_flow": "process_flow",
    "capability_cards": "four_columns",
    "integration_timeline": "two_columns",
    "image_device_mockup": "title",
}


def _cap(size: int, aggressive: bool) -> int:
    multiplier = 0.8 if aggressive else 1.0
    return max(10, int(size * multiplier))


def _normalize_title_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    normalized["title"] = _truncate_presentation_text(slide.get("title"), max_len=_cap(34, aggressive))
    normalized["subtitle"] = _truncate_presentation_text(slide.get("subtitle"), max_len=_cap(64, aggressive))
    footer = _truncate_presentation_text(slide.get("footer"), max_len=_cap(30, aggressive))
    if footer:
        normalized["footer"] = footer
    return normalized


def _normalize_agenda_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    normalized["title"] = _truncate_presentation_text(slide.get("title") or "Agenda", max_len=_cap(20, aggressive))
    normalized["items"] = _compact_bullet_lines(
        slide.get("items") or slide.get("bullets") or [],
        max_items=6 if not aggressive else 5,
        max_line_len=_cap(34, aggressive),
    )
    subtitle = _truncate_presentation_text(slide.get("subtitle"), max_len=_cap(44, aggressive))
    if subtitle:
        normalized["subtitle"] = subtitle
    return normalized


def _normalize_section_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    normalized["title"] = _truncate_presentation_text(slide.get("title"), max_len=_cap(30, aggressive))
    subtitle = _truncate_presentation_text(slide.get("subtitle"), max_len=_cap(40, aggressive))
    if subtitle:
        normalized["subtitle"] = subtitle
    return normalized


def _normalize_quote_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    normalized["quote"] = _truncate_presentation_text(slide.get("quote"), max_len=_cap(150, aggressive))
    author = _truncate_presentation_text(slide.get("author"), max_len=_cap(22, aggressive))
    title = _truncate_presentation_text(slide.get("title"), max_len=_cap(26, aggressive))
    if author:
        normalized["author"] = author
    if title:
        normalized["title"] = title
    return normalized


def _titled_visual_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> None:
    normalized["title"] = _truncate_presentation_text(slide.get("title"), max_len=_cap(30, aggressive))
    subtitle = _truncate_presentation_text(slide.get("subtitle"), max_len=_cap(42, aggressive))
    if subtitle:
        normalized["subtitle"] = subtitle


def _add_insight(slide: dict[str, Any], normalized: dict[str, Any], max_len: int) -> dict[str, Any]:
    insight = _truncate_presentation_text(slide.get("insight") or slide.get("caption"), max_len=max_len)
    if insight:
        normalized["insight"] = insight
    return normalized


def _normalize_chart_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    _titled_visual_slide(slide, normalized, aggressive)
    normalized["chart"] = _normalize_chart_payload(
        slide.get("chart") or slide, fallback_title=normalized.get("title") or "Chart"
    )
    return _add_insight(slide, normalized, _cap(56, aggressive))


def _normalize_table_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    _titled_visual_slide(slide, normalized, aggressive)
    normalized["table"] = _normalize_table_payload(
        slide.get("table") or slide, max_rows=4 if not aggressive else 3, max_cols=4
    )
    return _add_insight(slide, normalized, _cap(48, aggressive))


def _normalize_process_flow_slide(
    slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool
) -> dict[str, Any]:
    _titled_visual_slide(slide, normalized, aggressive)
    normalized["steps"] = _normalize_diagram_steps(
        slide.get("steps") or slide.get("nodes") or slide.get("items") or slide.get("bullets") or [],
        max_steps=4 if not aggressive else 3,
    )
    return _add_insight(slide, normalized, _cap(48, aggressive))


def _normalize_columns_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    layout = normalized["layout_type"]
    normalized["title"] = _truncate_presentation_text(
        slide.get("title"), max_len=_cap(28 if layout != "four_columns" else 26, aggressive)
    )
    columns = slide.get("columns") if isinstance(slide.get("columns"), list) else []
    column_specs = {
        "two_columns": (2, _cap(18, aggressive), 4 if not aggressive else 3, _cap(30, aggressive)),
        "three_columns": (3, _cap(16, aggressive), 3, _cap(24, aggressive)),
        "four_columns": (4, _cap(16, aggressive), 3 if not aggressive else 2, _cap(20, aggressive)),
    }
    count, label_len, body_items, body_line_len = column_specs[layout]
    normalized["columns"] = [
        _normalize_column_payload(column, label_len=label_len, body_items=body_items, body_line_len=body_line_len)
        for column in columns[:count]
    ]
    return normalized


def _normalize_bullets_slide(slide: dict[str, Any], normalized: dict[str, Any], aggressive: bool) -> dict[str, Any]:
    normalized["title"] = _truncate_presentation_text(slide.get("title"), max_len=_cap(30, aggressive))
    normalized["bullets"] = _compact_bullet_lines(
        slide.get("bullets") or slide.get("items") or slide.get("body") or slide.get("text") or [],
        max_items=5 if not aggressive else 4,
        max_line_len=_cap(48, aggressive),
    )
    return normalized


_SLIDE_NORMALIZERS = {
    "title": _normalize_title_slide,
    "agenda": _normalize_agenda_slide,
    "section": _normalize_section_slide,
    "quote": _normalize_quote_slide,
    "chart": _normalize_chart_slide,
    "table": _normalize_table_slide,
    "process_flow": _normalize_process_flow_slide,
    "two_columns": _normalize_columns_slide,
    "three_columns": _normalize_columns_slide,
    "four_columns": _normalize_columns_slide,
}


def _normalize_slide_spec(raw_slide: Any, *, aggressive: bool = False) -> dict[str, Any]:
    slide = dict(raw_slide) if isinstance(raw_slide, dict) else {}
    layout = (
        str(slide.get("layout_type") or "").strip().lower()
        or _ROLE_LAYOUTS.get(str(slide.get("role") or "").strip().lower(), "")
        or "bullets"
    )
    normalize = _SLIDE_NORMALIZERS.get(layout, _normalize_bullets_slide)
    return normalize(slide, {"layout_type": layout}, aggressive)


__all__ = [name for name in vars() if name.startswith("_") and not name.startswith("__")]
