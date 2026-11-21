"""Excel workbooks (openpyxl): element paths and edits (descriptors: ``sheets_describe``, views: ``sheets_views``).

Paths: ``/``, ``/Sheet1`` or ``/sheet[n]``, ``/Sheet1/B4``, ``/Sheet1/A1:C9``, ``/Sheet1/chart[n]``,
``/Sheet1/row[n]``; ``Sheet1!B4`` is accepted as well. Values are data, always (a leading ``=`` stays text);
formulas are written only through the ``formula`` property.

Generated Excel scripts import this module (``apply_cell_props``), so those names stay here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.cell import coordinate_from_string, range_boundaries

from .paths import (
    ELEMENT_NOT_FOUND,
    INVALID_REQUEST,
    UNSUPPORTED_ELEMENT,
    OfficeEngineError,
    flag,
    hex_color,
    parse_path,
    points,
)

_CELL = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+$")
_RANGE = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+:\$?[A-Za-z]{1,3}\$?\d+$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
ERROR_VALUES = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}


@dataclass(slots=True)
class Node:
    kind: str
    path: str
    obj: Any
    sheet: Any = None


def normalize_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw.startswith("/") and "!" in raw:
        sheet, _, ref = raw.rpartition("!")
        return f"/{sheet.strip(chr(39))}/{ref}"
    return raw


def _sheet(workbook: Any, segment: Any) -> Any:
    if segment.name == "sheet" and segment.index:
        if segment.index > len(workbook.worksheets):
            raise OfficeEngineError(ELEMENT_NOT_FOUND, f"/sheet[{segment.index}]")
        return workbook.worksheets[segment.index - 1]
    name = segment.name if segment.index is None and not segment.key else f"{segment.name}[{segment.index or segment.key}]"
    if name not in workbook.sheetnames:
        raise OfficeEngineError(ELEMENT_NOT_FOUND, f"/{name}")
    return workbook[name]


def resolve(workbook: Any, path: str) -> Node:
    segments = parse_path(normalize_path(path))
    if not segments:
        return Node("workbook", "/", workbook)
    worksheet = _sheet(workbook, segments[0])
    node = Node("sheet", f"/{worksheet.title}", worksheet, worksheet)
    if len(segments) == 1:
        return node
    if len(segments) > 2:
        raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
    token = segments[1]
    if token.name == "chart" and token.index:
        charts = list(worksheet._charts)
        if token.index > len(charts):
            raise OfficeEngineError(ELEMENT_NOT_FOUND, path)
        return Node("chart", f"{node.path}/chart[{token.index}]", charts[token.index - 1], worksheet)
    if token.name == "row" and token.index:
        return Node("row", f"{node.path}/row[{token.index}]", token.index, worksheet)
    ref = token.name.replace("$", "").upper()
    if _CELL.match(ref):
        return Node("cell", f"{node.path}/{ref}", worksheet[ref], worksheet)
    if _RANGE.match(ref):
        return Node("range", f"{node.path}/{ref}", ref, worksheet)
    raise OfficeEngineError(ELEMENT_NOT_FOUND, path)


def _cells(worksheet: Any, ref: str) -> Iterable[Any]:
    for row in worksheet[ref]:
        yield from row


# --- edits -------------------------------------------------------------------------------------------------


def set_literal(cell: Any, value: Any) -> None:
    """Store ``value`` as data. openpyxl turns any string starting with ``=`` into a formula; a data value
    (cell values, template data) must never become one — formulas come only from the ``formula`` property."""
    cell.value = coerce_value(value)
    if isinstance(cell.value, str) and cell.value.startswith("="):
        cell.data_type = "s"


def coerce_value(value: Any) -> Any:
    if isinstance(value, str) and _NUMBER.match(value.strip()):
        number = float(value)
        return int(number) if number.is_integer() and "." not in value else number
    return value


def apply_cell_props(cell: Any, props: dict[str, Any]) -> None:
    if "value" in props:
        set_literal(cell, props["value"])
    if props.get("formula"):
        formula = str(props["formula"]).strip()
        cell.value = formula if formula.startswith("=") else f"={formula}"
    number_format = props.get("numFmt", props.get("number_format"))
    if number_format:
        cell.number_format = str(number_format)
    font_changes: dict[str, Any] = {}
    for key, value in props.items():
        name = key.removeprefix("font.")
        if name == "bold":
            font_changes["b"] = flag(value)
        elif name == "italic":
            font_changes["i"] = flag(value)
        elif name == "size":
            font_changes["sz"] = points(value)
        elif name == "color":
            font_changes["color"] = "FF" + hex_color(value)
        elif key in {"font", "font.name"}:
            font_changes["name"] = str(value)
    if font_changes:
        current = cell.font
        cell.font = Font(
            name=font_changes.get("name", current.name), sz=font_changes.get("sz", current.sz),
            b=font_changes.get("b", current.b), i=font_changes.get("i", current.i), u=current.u,
            color=font_changes.get("color", current.color),
        )
    if props.get("fill"):
        color = "FF" + hex_color(props["fill"])
        cell.fill = PatternFill(fill_type="solid", fgColor=color, bgColor=color)
    horizontal = props.get("alignment.horizontal", props.get("align"))
    vertical = props.get("alignment.vertical", props.get("valign"))
    wrap = props.get("wrap", props.get("alignment.wrap_text"))
    if horizontal or vertical or wrap is not None:
        current_alignment = cell.alignment
        cell.alignment = Alignment(
            horizontal=str(horizontal) if horizontal else current_alignment.horizontal,
            vertical={"middle": "center"}.get(str(vertical), str(vertical)) if vertical else current_alignment.vertical,
            wrap_text=flag(wrap) if wrap is not None else current_alignment.wrap_text,
        )
    if props.get("border"):
        side = Side(style=str(props["border"]) if str(props["border"]) != "true" else "thin")
        cell.border = Border(left=side, right=side, top=side, bottom=side)


def set_props(workbook: Any, node: Node, props: dict[str, Any]) -> None:
    if node.kind == "cell":
        apply_cell_props(node.obj, props)
    elif node.kind == "range":
        values = props.get("values")
        cells_props = {key: value for key, value in props.items() if key != "values"}
        for row_offset, row in enumerate(node.sheet[node.obj]):
            for col_offset, cell in enumerate(row):
                if isinstance(values, list) and row_offset < len(values) and isinstance(values[row_offset], list) \
                        and col_offset < len(values[row_offset]):
                    set_literal(cell, values[row_offset][col_offset])
                if cells_props:
                    apply_cell_props(cell, cells_props)
    elif node.kind == "sheet":
        name = props.get("name", props.get("title"))
        if name:
            node.obj.title = str(name)
        if props.get("tabColor"):
            node.obj.sheet_properties.tabColor = hex_color(props["tabColor"])
        if "freeze" in props:
            node.obj.freeze_panes = str(props["freeze"]) or None
        for key, value in props.items():
            match = re.fullmatch(r"col\.([A-Za-z]{1,3})\.width", key)
            if match:
                node.obj.column_dimensions[match.group(1).upper()].width = float(value)
    elif node.kind == "chart":
        if "title" in props:
            node.obj.title = str(props["title"])
    else:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"cannot set properties on {node.kind}")


def remove(workbook: Any, node: Node) -> None:
    if node.kind == "sheet":
        if len(workbook.worksheets) == 1:
            raise OfficeEngineError(UNSUPPORTED_ELEMENT, "a workbook keeps at least one sheet")
        workbook.remove(node.obj)
    elif node.kind == "chart":
        node.sheet._charts.remove(node.obj)
    elif node.kind == "row":
        node.sheet.delete_rows(node.obj)
    elif node.kind == "cell":
        node.obj.value = None
    elif node.kind == "range":
        for cell in _cells(node.sheet, node.obj):
            cell.value = None
    else:
        raise OfficeEngineError(UNSUPPORTED_ELEMENT, f"{node.kind} cannot be removed")


def add_sheet(workbook: Any, name: str = "", index: int | None = None) -> Any:
    if name and name in workbook.sheetnames:
        raise OfficeEngineError(INVALID_REQUEST, f"sheet {name!r} exists")
    return workbook.create_sheet(title=name or None, index=(index - 1) if index else None)


def add_row(worksheet: Any, values: list[Any], index: int | None = None) -> None:
    if index:
        worksheet.insert_rows(index)
        for column, value in enumerate(values, start=1):
            set_literal(worksheet.cell(row=index, column=column), value)
    else:
        row = worksheet.max_row + 1 if any(cell.value is not None for cell in worksheet[worksheet.max_row]) else worksheet.max_row
        for column, value in enumerate(values, start=1):
            set_literal(worksheet.cell(row=row, column=column), value)


def cell_bounds(ref: str) -> tuple[int, int, int, int]:
    """``"A1:C9"`` → (min_col, min_row, max_col, max_row)."""
    return range_boundaries(ref.replace("$", ""))


def split_cell(ref: str) -> tuple[str, int]:
    return coordinate_from_string(ref.replace("$", ""))


__all__ = [
    "ERROR_VALUES",
    "Node",
    "add_row",
    "add_sheet",
    "apply_cell_props",
    "cell_bounds",
    "coerce_value",
    "normalize_path",
    "remove",
    "resolve",
    "set_literal",
    "set_props",
    "split_cell",
]
