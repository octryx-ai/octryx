"""Excel features beyond cells: native charts, data validation, conditional formats, autofilter, sparklines,
and the pivot-style summary.

Sparklines: openpyxl neither writes nor keeps the x14 ``sparklineGroups`` extension, so they are carried
around it — read from the package before openpyxl loads it, and written back into each sheet's ``extLst``
after openpyxl saved (:func:`read_sparklines`, :func:`write_sparklines`). An edit through the tools therefore
keeps a workbook's sparklines.

Pivot tables: openpyxl cannot create a pivot cache, so a pivot request renders a live summary table of
``SUMIFS``/``COUNTIFS``/``AVERAGEIFS`` formulas grouped by the ``rows`` field (``pivot_mode:
"formula_summary"``).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from lxml import etree
from openpyxl.chart import AreaChart, BarChart, DoughnutChart, LineChart, PieChart, RadarChart, Reference, ScatterChart
from openpyxl.chart.series import Series
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation

from .charts import ChartSpec
from .paths import INVALID_REQUEST, OfficeEngineError, flag, hex_color, length_emu
from .sheets import cell_bounds
from .xlsx_sparkline_xml import _X14, _XM, _sheet_parts, _with_sparklines


def _split_ref(workbook: Any, worksheet: Any, ref: str) -> tuple[Any, str]:
    sheet_name, _, cells = ref.rpartition("!")
    if not sheet_name:
        return worksheet, cells
    name = sheet_name.strip("'")
    if name not in workbook.sheetnames:
        raise OfficeEngineError(INVALID_REQUEST, f"unknown sheet {name!r} in range")
    return workbook[name], cells


def _literal_table(worksheet: Any, spec: ChartSpec) -> str:
    """Write literal chart data beside the used range; returns the written range."""
    start_col = worksheet.max_column + 2
    worksheet.cell(row=1, column=start_col, value="")
    for offset, (name, _) in enumerate(spec.series, start=1):
        worksheet.cell(row=1, column=start_col + offset, value=name)
    for row_offset, category in enumerate(spec.categories, start=2):
        worksheet.cell(row=row_offset, column=start_col, value=category)
        for offset, (_, values) in enumerate(spec.series, start=1):
            if row_offset - 2 < len(values):
                worksheet.cell(row=row_offset, column=start_col + offset, value=values[row_offset - 2])
    end_col = start_col + len(spec.series)
    end_row = 1 + len(spec.categories)
    return f"{get_column_letter(start_col)}1:{get_column_letter(end_col)}{end_row}"


def _chart_object(chart_type: str) -> Any:
    if chart_type in {"column", "column_stacked", "bar", "bar_stacked"}:
        chart = BarChart()
        chart.type = "col" if chart_type.startswith("column") else "bar"
        if chart_type.endswith("stacked"):
            chart.grouping = "stacked"
            chart.overlap = 100
        return chart
    if chart_type in {"area", "area_stacked"}:
        chart = AreaChart()
        if chart_type == "area_stacked":
            chart.grouping = "stacked"
        return chart
    return {"line": LineChart, "pie": PieChart, "doughnut": DoughnutChart, "scatter": ScatterChart,
            "radar": RadarChart}[chart_type]()


def add_chart(workbook: Any, worksheet: Any, spec: ChartSpec, props: dict[str, Any]) -> dict[str, Any]:
    source_sheet, ref = _split_ref(workbook, worksheet, spec.data_range) if spec.data_range else (worksheet, "")
    if not ref:
        if not spec.series:
            raise OfficeEngineError(INVALID_REQUEST, "an Excel chart needs data_range or series values")
        ref = _literal_table(worksheet, spec)
    min_col, min_row, max_col, max_row = cell_bounds(ref)
    if max_col <= min_col or max_row <= min_row:
        raise OfficeEngineError(INVALID_REQUEST, "data_range needs a header row and a category column")
    chart = _chart_object(spec.chart_type)
    categories = Reference(source_sheet, min_col=min_col, min_row=min_row + 1, max_row=max_row)
    if spec.chart_type == "scatter":
        for column in range(min_col + 1, max_col + 1):
            values = Reference(source_sheet, min_col=column, min_row=min_row, max_row=max_row)
            chart.series.append(Series(values, categories, title_from_data=True))
    else:
        data = Reference(source_sheet, min_col=min_col + 1, min_row=min_row, max_col=max_col, max_row=max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
    if spec.title:
        chart.title = spec.title
    if spec.legend == "none":
        chart.legend = None
    elif chart.legend is not None:
        chart.legend.position = {"bottom": "b", "top": "t", "left": "l", "right": "r", "corner": "tr"}[spec.legend]
    for position, series in enumerate(chart.series):
        if spec.colors and spec.chart_type not in {"pie", "doughnut"}:
            color = spec.colors[position % len(spec.colors)]
            if spec.chart_type in {"line", "scatter", "radar"}:
                series.graphicalProperties.line.solidFill = color
            else:
                series.graphicalProperties.solidFill = color
    if spec.chart_type not in {"pie", "doughnut"}:
        # openpyxl 3.1 marks axes as deleted unless told otherwise; Excel then draws no axes.
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        if spec.axis_title:
            chart.y_axis.title = spec.axis_title
        if spec.category_title:
            chart.x_axis.title = spec.category_title
    chart.width = length_emu(props.get("width") or "15cm") / 360000
    chart.height = length_emu(props.get("height") or "7.5cm") / 360000
    anchor = str(props.get("anchor") or props.get("position") or props.get("x") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}\d+", anchor):
        anchor = f"{get_column_letter(worksheet.max_column + 2)}2"
    worksheet.add_chart(chart, anchor)
    return {"anchor": anchor, "data_range": f"{quote_sheetname(source_sheet.title)}!{ref}"}


def add_validation(worksheet: Any, props: dict[str, Any]) -> None:
    sqref = str(props.get("sqref") or props.get("range") or "").strip()
    if not sqref:
        raise OfficeEngineError(INVALID_REQUEST, "a validation needs sqref")
    kind = str(props.get("type") or "list").strip()
    formula1 = props.get("formula1")
    values = props.get("values", props.get("list"))
    if kind == "list" and values and not formula1:
        items = values if isinstance(values, list) else str(values).split(",")
        formula1 = '"' + ",".join(str(item).strip() for item in items) + '"'
    validation = DataValidation(
        type=kind, operator=props.get("operator"), formula1=None if formula1 is None else str(formula1),
        formula2=None if props.get("formula2") is None else str(props.get("formula2")),
        allow_blank=flag(props.get("allowBlank", True)),
        showErrorMessage=flag(props.get("showError", True)),
        error=props.get("error"), prompt=props.get("prompt"),
    )
    validation.add(sqref)
    worksheet.add_data_validation(validation)


def add_conditional_format(worksheet: Any, props: dict[str, Any]) -> None:
    sqref = str(props.get("sqref") or props.get("range") or "").strip()
    kind = str(props.get("type") or props.get("cf_type") or "").strip()
    if not sqref or not kind:
        raise OfficeEngineError(INVALID_REQUEST, "a conditional format needs sqref and type")
    fill = PatternFill(fill_type="solid", fgColor="FF" + hex_color(props["fill"]), bgColor="FF" + hex_color(props["fill"])) if props.get("fill") else None
    font = Font(color="FF" + hex_color(props["color"])) if props.get("color") else None
    lowered = kind.lower()
    if lowered == "cellis":
        formulas = props.get("formula") if isinstance(props.get("formula"), list) else [str(props.get("formula") or props.get("value") or "0")]
        rule = CellIsRule(operator=str(props.get("operator") or "greaterThan"), formula=formulas, fill=fill, font=font)
    elif lowered in {"expression", "formula"}:
        rule = FormulaRule(formula=[str(props.get("formula") or "")], fill=fill, font=font)
    elif lowered == "colorscale":
        rule = ColorScaleRule(start_type="min", start_color=hex_color(props.get("start_color") or props.get("minColor") or "F8696B"),
                              end_type="max", end_color=hex_color(props.get("end_color") or props.get("maxColor") or "63BE7B"))
    elif lowered == "databar":
        rule = DataBarRule(start_type="min", end_type="max", color=hex_color(props.get("color") or props.get("barColor") or "638EC6"))
    else:
        raise OfficeEngineError(INVALID_REQUEST, "conditional format types: cellIs, expression, colorScale, dataBar")
    worksheet.conditional_formatting.add(sqref, rule)


def set_autofilter(worksheet: Any, ref: str) -> None:
    worksheet.auto_filter.ref = str(ref).strip()


def pivot_summary(workbook: Any, worksheet: Any, props: dict[str, Any]) -> dict[str, Any]:
    """A grouped summary of ``source`` by the first ``rows`` field, as live formulas."""
    source = str(props.get("source") or "").strip()
    source_sheet, ref = _split_ref(workbook, worksheet, source)
    min_col, min_row, max_col, max_row = cell_bounds(ref)
    headers = {str(source_sheet.cell(row=min_row, column=col).value or "").strip(): col for col in range(min_col, max_col + 1)}
    rows_field = _first(props.get("rows"))
    value_field = _first(props.get("values"))
    if rows_field not in headers:
        raise OfficeEngineError(INVALID_REQUEST, "pivot rows must name a header of the source range")
    function = "SUM"
    match = re.fullmatch(r"(sum|count|average|avg)\((.+)\)", value_field or "", re.IGNORECASE)
    if match:
        function = {"avg": "AVERAGE"}.get(match.group(1).lower(), match.group(1).upper())
        value_field = match.group(2).strip()
    if function != "COUNT" and value_field not in headers:
        raise OfficeEngineError(INVALID_REQUEST, "pivot values must name a header of the source range")
    group_col = headers[rows_field]
    keys: list[Any] = []
    for row in range(min_row + 1, max_row + 1):
        key = source_sheet.cell(row=row, column=group_col).value
        if key is not None and key not in keys:
            keys.append(key)
    anchor = str(props.get("position") or "").strip().upper() or f"{get_column_letter(worksheet.max_column + 2)}1"
    target_col, target_row = cell_bounds(anchor)[:2]
    prefix = f"{quote_sheetname(source_sheet.title)}!"
    group_range = f"{prefix}${get_column_letter(group_col)}${min_row + 1}:${get_column_letter(group_col)}${max_row}"
    worksheet.cell(row=target_row, column=target_col, value=rows_field).font = Font(b=True)
    label = value_field if function == "SUM" else f"{function.title()} of {value_field or rows_field}"
    worksheet.cell(row=target_row, column=target_col + 1, value=label).font = Font(b=True)
    for offset, key in enumerate(keys, start=1):
        key_cell = worksheet.cell(row=target_row + offset, column=target_col, value=key)
        criterion = key_cell.coordinate
        if function == "COUNT":
            formula = f"=COUNTIFS({group_range},{criterion})"
        else:
            value_col = get_column_letter(headers[value_field])
            value_range = f"{prefix}${value_col}${min_row + 1}:${value_col}${max_row}"
            formula = f"={function}IFS({value_range},{group_range},{criterion})"
        worksheet.cell(row=target_row + offset, column=target_col + 1, value=formula)
    return {"pivot_mode": "formula_summary", "groups": len(keys), "anchor": anchor}


def _first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value or "").split(",")[0].strip()


# --- sparklines --------------------------------------------------------------------------------------------


def sparkline_group(worksheet_title: str, props: dict[str, Any]) -> str:
    cell = str(props.get("cell") or "").strip()
    data_range = str(props.get("range") or props.get("data_range") or "").strip()
    if not cell or not data_range:
        raise OfficeEngineError(INVALID_REQUEST, "a sparkline needs cell and range")
    if "!" not in data_range:
        data_range = f"{quote_sheetname(worksheet_title)}!{data_range}"
    kind = str(props.get("type") or "line").lower()
    type_attr = {"column": ' type="column"', "winloss": ' type="stacked"', "stacked": ' type="stacked"'}.get(kind, "")
    flag_props = {"markers": "markers", "high": "highpoint", "low": "lowpoint", "first": "firstpoint", "last": "lastpoint"}
    flags = "".join(f' {attr}="1"' for attr, key in flag_props.items() if flag(props.get(key, props.get(attr, False))))
    color = hex_color(props.get("color") or "376092")
    return (
        f'<x14:sparklineGroup xmlns:x14="{_X14}" xmlns:xm="{_XM}" displayEmptyCellsAs="gap"{type_attr}{flags}>'
        f'<x14:colorSeries rgb="FF{color}"/><x14:colorNegative rgb="FFD00000"/><x14:colorAxis rgb="FF000000"/>'
        '<x14:colorMarkers rgb="FFD00000"/><x14:colorFirst rgb="FFD00000"/><x14:colorLast rgb="FFD00000"/>'
        '<x14:colorHigh rgb="FFD00000"/><x14:colorLow rgb="FFD00000"/>'
        f"<x14:sparklines><x14:sparkline><xm:f>{escape(data_range)}</xm:f><xm:sqref>{escape(cell)}</xm:sqref>"
        "</x14:sparkline></x14:sparklines></x14:sparklineGroup>"
    )


def read_sparklines(data: bytes) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name, part in _sheet_parts(archive).items():
            if part not in archive.namelist():
                continue
            root = etree.fromstring(archive.read(part))
            found = [etree.tostring(group, encoding="unicode") for group in root.iter(f"{{{_X14}}}sparklineGroup")]
            if found:
                groups[name] = found
    return groups


def write_sparklines(path: str | Path, groups: dict[str, list[str]]) -> None:
    if not any(groups.values()):
        return
    target = Path(path)
    with zipfile.ZipFile(target) as archive:
        parts = _sheet_parts(archive)
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
    by_part = {parts[name]: items for name, items in groups.items() if name in parts and items}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as rebuilt:
        for item, payload in entries:
            if item.filename in by_part:
                payload = _with_sparklines(payload, by_part[item.filename])
            rebuilt.writestr(item, payload)
    target.write_bytes(output.getvalue())


__all__ = [
    "add_chart",
    "add_conditional_format",
    "add_validation",
    "pivot_summary",
    "read_sparklines",
    "set_autofilter",
    "sparkline_group",
    "write_sparklines",
]
