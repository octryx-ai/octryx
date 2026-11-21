"""Excel descriptors (openpyxl): what ``get`` and ``query`` report for the workbook, sheets, cells and charts."""

from __future__ import annotations

from typing import Any

from .sheets import Node


def cell_descriptor(cell: Any, path: str) -> dict[str, Any]:
    value = cell.value
    is_formula = isinstance(value, str) and value.startswith("=")
    font = cell.font
    descriptor = {
        "type": "cell",
        "path": path,
        "ref": cell.coordinate,
        "value": value if not is_formula else None,
        "formula": value if is_formula else None,
        "text": "" if value is None else str(value),
        "number_format": cell.number_format,
        "bold": bool(font.b) if font is not None else None,
    }
    if font is not None and font.color is not None and isinstance(font.color.rgb, str):
        descriptor["color"] = font.color.rgb[-6:]
    fill = cell.fill
    if fill is not None and fill.fill_type == "solid" and isinstance(fill.fgColor.rgb, str):
        descriptor["fill"] = fill.fgColor.rgb[-6:]
    return descriptor


def chart_title(chart: Any) -> str:
    title = getattr(chart, "title", None)
    if title is None or isinstance(title, str):
        return title or ""
    rich = getattr(getattr(title, "tx", None), "rich", None)
    if rich is None:
        return ""
    return "".join(run.t or "" for paragraph in rich.p for run in (paragraph.r or []))


def chart_descriptor(chart: Any, path: str) -> dict[str, Any]:
    anchor = getattr(getattr(chart.anchor, "_from", None), "col", None)
    return {
        "type": "chart",
        "path": path,
        "chart_type": type(chart).__name__,
        "title": chart_title(chart),
        "series": len(chart.series),
        "anchor_col": anchor,
    }


def sheet_descriptor(worksheet: Any) -> dict[str, Any]:
    return {
        "type": "sheet",
        "path": f"/{worksheet.title}",
        "name": worksheet.title,
        "text": worksheet.title,
        "dimensions": worksheet.dimensions,
        "max_row": worksheet.max_row,
        "max_col": worksheet.max_column,
        "charts": len(worksheet._charts),
        "freeze": worksheet.freeze_panes,
    }


def describe(node: Node, depth: int) -> dict[str, Any]:
    if node.kind == "workbook":
        result: dict[str, Any] = {"type": "workbook", "path": "/", "sheets": node.obj.sheetnames}
        if depth > 1:
            result["children"] = [sheet_descriptor(worksheet) for worksheet in node.obj.worksheets]
        return result
    if node.kind == "sheet":
        result = sheet_descriptor(node.obj)
        if depth > 1:
            result["charts_detail"] = [chart_descriptor(chart, f"{node.path}/chart[{i}]") for i, chart in enumerate(node.obj._charts, start=1)]
        return result
    if node.kind == "cell":
        return cell_descriptor(node.obj, node.path)
    if node.kind == "chart":
        return chart_descriptor(node.obj, node.path)
    if node.kind == "row":
        values = [cell.value for cell in node.sheet[node.obj]]
        return {"type": "row", "path": node.path, "values": values, "text": " | ".join("" if v is None else str(v) for v in values)}
    rows = [[cell.value for cell in row] for row in node.sheet[node.obj]]
    return {"type": "range", "path": node.path, "ref": node.obj, "values": rows}


def iter_descriptors(workbook: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for worksheet in workbook.worksheets:
        found.append(sheet_descriptor(worksheet))
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    found.append(cell_descriptor(cell, f"/{worksheet.title}/{cell.coordinate}"))
        for index, chart in enumerate(worksheet._charts, start=1):
            found.append(chart_descriptor(chart, f"/{worksheet.title}/chart[{index}]"))
    return found


__all__ = [
    "cell_descriptor",
    "chart_descriptor",
    "chart_title",
    "describe",
    "iter_descriptors",
    "sheet_descriptor",
]
