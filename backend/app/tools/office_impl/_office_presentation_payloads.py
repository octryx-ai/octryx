"""Chart, table, column and diagram payload normalization for presentation slides."""

from __future__ import annotations

from typing import Any

from ._office_presentation_text import _compact_bullet_lines, _truncate_presentation_text


def _normalize_column_payload(column: Any, *, label_len: int, body_items: int, body_line_len: int) -> dict[str, str]:
    payload = dict(column) if isinstance(column, dict) else {}
    label = _truncate_presentation_text(
        payload.get("label") or payload.get("title") or payload.get("heading") or "", max_len=label_len
    )
    body_lines = _compact_bullet_lines(
        payload.get("body") or payload.get("text") or payload.get("items") or payload.get("bullets") or "",
        max_items=body_items,
        max_line_len=body_line_len,
    )
    return {"label": label, "body": "\n".join(f"• {line}" for line in body_lines if line)}


def _normalize_chart_payload(raw_chart: Any, *, fallback_title: str = "") -> dict[str, Any]:
    payload = dict(raw_chart) if isinstance(raw_chart, dict) else {}
    categories = [
        _truncate_presentation_text(item, max_len=18)
        for item in (payload.get("categories") or payload.get("labels") or [])
        if _truncate_presentation_text(item, max_len=18)
    ]
    series: list[dict[str, Any]] = []
    raw_series = payload.get("series")
    if isinstance(raw_series, list):
        iterable = (
            (item.get("name") or item.get("label") or "Series", item.get("values"))
            for item in raw_series
            if isinstance(item, dict)
        )
    elif isinstance(raw_series, dict):
        iterable = raw_series.items()
    else:
        iterable = []
    for name, values in iterable:
        if isinstance(values, list) and values:
            series.append(
                {
                    "name": _truncate_presentation_text(name, max_len=28) or "Series",
                    "values": [str(value) for value in values],
                }
            )
    chart: dict[str, Any] = {
        "chart_type": str(payload.get("chart_type") or payload.get("type") or "column").strip().lower() or "column",
        "title": _truncate_presentation_text(payload.get("title") or fallback_title, max_len=36),
        "categories": categories,
        "series": series,
        "data": str(payload.get("data") or "").strip(),
        "legend": str(payload.get("legend") or "bottom").strip(),
        "x": str(payload.get("x") or "2.0cm").strip(),
        "y": str(payload.get("y") or "4.4cm").strip(),
        "width": str(payload.get("width") or "20.5cm").strip(),
        "height": str(payload.get("height") or "9.5cm").strip(),
        "axis_title": str(payload.get("axis_title") or payload.get("value_axis_title") or "").strip(),
        "category_title": str(payload.get("category_title") or payload.get("cat_title") or "").strip(),
    }
    colors = str(payload.get("colors") or "").strip()
    if colors:
        chart["colors"] = colors
    return chart


def _normalize_table_payload(raw_table: Any, *, max_rows: int = 4, max_cols: int = 4) -> dict[str, Any]:
    payload = dict(raw_table) if isinstance(raw_table, dict) else {}
    headers = [
        _truncate_presentation_text(item, max_len=18)
        for item in (payload.get("headers") or [])
        if _truncate_presentation_text(item, max_len=18)
    ][:max_cols]
    rows: list[list[str]] = []
    for row in (payload.get("rows") or [])[:max_rows]:
        if isinstance(row, list):
            cleaned_row = [
                _truncate_presentation_text(cell, max_len=20)
                for cell in row[:max_cols]
                if _truncate_presentation_text(cell, max_len=20) or str(cell or "").strip() == ""
            ]
            if cleaned_row:
                rows.append(cleaned_row)
    return {
        "headers": headers,
        "rows": rows,
        "x": str(payload.get("x") or "2.0cm").strip(),
        "y": str(payload.get("y") or "4.6cm").strip(),
        "width": str(payload.get("width") or "20.5cm").strip(),
        "height": str(payload.get("height") or "8.8cm").strip(),
    }


def _normalize_diagram_steps(raw_steps: Any, *, max_steps: int = 4) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    if not isinstance(raw_steps, list):
        return steps
    for item in raw_steps:
        if len(steps) >= max_steps:
            break
        if isinstance(item, dict):
            title = _truncate_presentation_text(
                item.get("title") or item.get("label") or item.get("heading") or "", max_len=26
            )
            body = _truncate_presentation_text(
                item.get("body") or item.get("text") or item.get("description") or "", max_len=44
            )
        else:
            title = _truncate_presentation_text(item, max_len=26)
            body = ""
        if title:
            steps.append({"title": title, "body": body})
    return steps


__all__ = [
    "_normalize_chart_payload",
    "_normalize_column_payload",
    "_normalize_diagram_steps",
    "_normalize_table_payload",
]
