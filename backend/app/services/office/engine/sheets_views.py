"""Excel views (openpyxl): text, outline, annotated and stats."""

from __future__ import annotations

from typing import Any

from .paths import text_window

DEFAULT_ROW_WINDOW = 200


def _display(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def text_view(workbook: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    sheets = []
    total = 0
    for worksheet in workbook.worksheets:
        rows = []
        for row in worksheet.iter_rows():
            cells = {cell.coordinate: _display(cell.value) for cell in row if cell.value is not None}
            if cells:
                total += len(cells)
                rows.append({"row": row[0].row, "cells": cells})
        window = text_window(rows, start=start, end=end, max_lines=max_lines or DEFAULT_ROW_WINDOW)
        sheets.append({"name": worksheet.title, "rows": window, "totalRows": len(rows)})
    return {"totalElements": total, "sheets": sheets}


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def outline_view(workbook: Any) -> dict[str, Any]:
    sheets = []
    for worksheet in workbook.worksheets:
        formulas = sum(1 for row in worksheet.iter_rows() for cell in row if _is_formula(cell.value))
        sheets.append({"name": worksheet.title, "rows": worksheet.max_row, "cols": worksheet.max_column,
                       "formulas": formulas, "charts": len(worksheet._charts), "dimensions": worksheet.dimensions})
    return {"sheets": sheets}


def annotated_view(workbook: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    lines: list[str] = []
    for worksheet in workbook.worksheets:
        lines.append(f"[{worksheet.title}] {worksheet.dimensions}, {len(worksheet._charts)} chart(s)")
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                kind = "formula" if _is_formula(cell.value) else "number" if isinstance(cell.value, (int, float)) else "text"
                fmt = f", {cell.number_format}" if cell.number_format != "General" else ""
                lines.append(f"    {worksheet.title}!{cell.coordinate} [{kind}{fmt}] {cell.value}")
    window = text_window(lines, start=start, end=end, max_lines=max_lines or DEFAULT_ROW_WINDOW * 5)
    return {"Content": "\n".join(window), "totalLines": len(lines)}


def stats_view(workbook: Any) -> dict[str, Any]:
    cells = formulas = 0
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    cells += 1
                    formulas += _is_formula(cell.value)
    return {
        "sheets": len(workbook.worksheets),
        "sheetNames": workbook.sheetnames,
        "cells": cells,
        "formulas": formulas,
        "charts": sum(len(worksheet._charts) for worksheet in workbook.worksheets),
        "mergedRanges": sum(len(worksheet.merged_cells.ranges) for worksheet in workbook.worksheets),
        "dataValidations": sum(len(worksheet.data_validations.dataValidation) for worksheet in workbook.worksheets),
        "conditionalFormats": sum(len(list(worksheet.conditional_formatting)) for worksheet in workbook.worksheets),
    }


__all__ = [
    "DEFAULT_ROW_WINDOW",
    "annotated_view",
    "outline_view",
    "stats_view",
    "text_view",
]
