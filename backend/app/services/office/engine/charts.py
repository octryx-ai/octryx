"""Native charts: one chart spec for PowerPoint, Word and the Excel chart builder.

A spec comes either structured (``chart_type``, ``categories``, ``series: [{name, values}]``) or as the flat
properties the tools always accepted (``chartType``, ``categories="Q1,Q2"``, ``series1="Revenue:12,16"``,
``data="Revenue:12,16;Cost:8,9"``). PowerPoint charts are python-pptx charts; Word charts are the same chart
XML (python-pptx's writer) stored as a Word chart part with its embedded workbook, so Word can edit the data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .paths import INVALID_REQUEST, OfficeEngineError, hex_color

CHART_TYPE_ALIASES = {
    "col": "column",
    "clustered_column": "column",
    "column_clustered": "column",
    "stacked_column": "column_stacked",
    "stackedcolumn": "column_stacked",
    "clustered_bar": "bar",
    "bar_clustered": "bar",
    "stacked_bar": "bar_stacked",
    "stackedbar": "bar_stacked",
    "line_markers": "line",
    "linemarkers": "line",
    "donut": "doughnut",
    "stacked_area": "area_stacked",
    "xy": "scatter",
    "xy_scatter": "scatter",
}
CHART_TYPES = (
    "column",
    "column_stacked",
    "bar",
    "bar_stacked",
    "line",
    "pie",
    "doughnut",
    "area",
    "area_stacked",
    "scatter",
    "radar",
)
LEGEND_POSITIONS = {"bottom", "top", "left", "right", "corner", "none"}


@dataclass(slots=True)
class ChartSpec:
    chart_type: str
    title: str = ""
    categories: list[str] = field(default_factory=list)
    series: list[tuple[str, list[float]]] = field(default_factory=list)
    legend: str = "bottom"
    data_range: str = ""
    colors: list[str] = field(default_factory=list)
    axis_title: str = ""
    category_title: str = ""


def normalize_chart_type(value: Any) -> str:
    key = re.sub(r"[\s-]+", "_", str(value or "column").strip().lower())
    key = CHART_TYPE_ALIASES.get(key, key)
    if key not in CHART_TYPES:
        raise OfficeEngineError(INVALID_REQUEST, f"unsupported chart type; supported: {', '.join(CHART_TYPES)}")
    return key


def _number(value: Any) -> float:
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise OfficeEngineError(INVALID_REQUEST, "chart values must be numbers") from exc


def _items(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _flat_series(text: str, fallback_name: str) -> tuple[str, list[float]]:
    name, _, values = str(text).rpartition(":")
    return (name.strip() or fallback_name, [_number(item) for item in _items(values)])


def chart_spec(props: dict[str, Any]) -> ChartSpec:
    spec = ChartSpec(chart_type=normalize_chart_type(props.get("chart_type") or props.get("chartType") or props.get("type")))
    spec.title = str(props.get("title") or "").strip()
    spec.categories = _items(props.get("categories"))
    spec.data_range = str(props.get("data_range") or props.get("dataRange") or props.get("range") or "").strip()
    legend = str(props.get("legend") or "bottom").strip().lower()
    spec.legend = legend if legend in LEGEND_POSITIONS else "bottom"
    spec.colors = [hex_color(item) for item in _items(props.get("colors"))]
    spec.axis_title = str(props.get("axis_title") or props.get("axisTitle") or "").strip()
    spec.category_title = str(props.get("category_title") or props.get("catTitle") or "").strip()
    for index, series in enumerate(props.get("series") or [], start=1):
        if isinstance(series, dict):
            values = [_number(item) for item in series.get("values") or [] if str(item).strip()]
            if values:
                spec.series.append((str(series.get("name") or f"Series {index}").strip(), values))
    numbered = sorted(
        (int(key[6:]), value) for key, value in props.items() if re.fullmatch(r"series\d+", str(key)) and value
    )
    for index, value in numbered:
        spec.series.append(_flat_series(str(value), f"Series {index}"))
    data = str(props.get("data") or "").strip()
    if data and not spec.series:
        for index, part in enumerate([item for item in data.split(";") if item.strip()], start=1):
            spec.series.append(_flat_series(part, f"Series {index}"))
    if spec.series and not spec.categories:
        spec.categories = [str(index) for index in range(1, max(len(values) for _, values in spec.series) + 1)]
    return spec


def _require_data(spec: ChartSpec) -> None:
    if not spec.series:
        raise OfficeEngineError(INVALID_REQUEST, "a chart needs at least one series with values")


def pptx_chart_type(chart_type: str) -> Any:
    from pptx.enum.chart import XL_CHART_TYPE

    return {
        "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "column_stacked": XL_CHART_TYPE.COLUMN_STACKED,
        "bar": XL_CHART_TYPE.BAR_CLUSTERED,
        "bar_stacked": XL_CHART_TYPE.BAR_STACKED,
        "line": XL_CHART_TYPE.LINE_MARKERS,
        "pie": XL_CHART_TYPE.PIE,
        "doughnut": XL_CHART_TYPE.DOUGHNUT,
        "area": XL_CHART_TYPE.AREA,
        "area_stacked": XL_CHART_TYPE.AREA_STACKED,
        "scatter": XL_CHART_TYPE.XY_SCATTER,
        "radar": XL_CHART_TYPE.RADAR,
    }[chart_type]


def pptx_chart_data(spec: ChartSpec) -> Any:
    from pptx.chart.data import CategoryChartData, XyChartData

    _require_data(spec)
    if spec.chart_type == "scatter":
        data = XyChartData()
        x_values = [_number(item) for item in spec.categories] if spec.categories else []
        for name, values in spec.series:
            series = data.add_series(name)
            for position, value in enumerate(values):
                series.add_data_point(x_values[position] if position < len(x_values) else position + 1, value)
        return data
    data = CategoryChartData()
    data.categories = spec.categories
    width = len(spec.categories)
    for name, values in spec.series:
        data.add_series(name, (values + [None] * width)[:width])
    return data


def format_chart(chart: Any, spec: ChartSpec) -> None:
    """Title, legend, series colours and axis titles on a python-pptx chart object."""
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_LEGEND_POSITION

    if spec.title:
        chart.has_title = True
        chart.chart_title.text_frame.text = spec.title
    else:
        chart.has_title = False
    if spec.legend == "none" or (len(spec.series) < 2 and spec.chart_type not in {"pie", "doughnut"}):
        chart.has_legend = False
    else:
        chart.has_legend = True
        chart.legend.position = getattr(XL_LEGEND_POSITION, spec.legend.upper())
        chart.legend.include_in_layout = False
    if spec.colors and spec.chart_type not in {"pie", "doughnut"}:
        for position, series in enumerate(chart.plots[0].series):
            color = RGBColor.from_string(spec.colors[position % len(spec.colors)])
            if spec.chart_type in {"line", "scatter", "radar"}:
                series.format.line.color.rgb = color
            else:
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = color
    if spec.chart_type in {"pie", "doughnut"}:
        return
    for axis_name, title in (("value_axis", spec.axis_title), ("category_axis", spec.category_title)):
        if not title:
            continue
        axis = getattr(chart, axis_name)
        axis.has_title = True
        axis.axis_title.text_frame.text = title


def add_pptx_chart(shapes: Any, spec: ChartSpec, *, x: int, y: int, cx: int, cy: int) -> Any:
    frame = shapes.add_chart(pptx_chart_type(spec.chart_type), x, y, cx, cy, pptx_chart_data(spec))
    format_chart(frame.chart, spec)
    return frame


_C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT_CHART = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
_CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_RT_CHART = f"{_R_NS}/chart"
_RT_PACKAGE = f"{_R_NS}/package"


def _next_chart_number(package: Any) -> int:
    used = {
        int(match.group(1))
        for part in package.iter_parts()
        if (match := re.fullmatch(r"/word/charts/chart(\d+)\.xml", str(part.partname)))
    }
    return max(used, default=0) + 1


def _next_docpr_id(document: Any) -> int:
    ids = [int(value) for value in document.element.body.xpath("//wp:docPr/@id") if str(value).isdigit()]
    return max(ids, default=0) + 1


def add_docx_chart(document: Any, spec: ChartSpec, *, paragraph: Any, cx: int, cy: int) -> None:
    """Append a native chart to ``paragraph`` (a python-docx paragraph)."""
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import parse_xml as parse_docx_xml
    from lxml import etree
    from pptx.chart.chart import Chart
    from pptx.chart.xmlwriter import ChartXmlWriter
    from pptx.oxml import parse_xml as parse_pptx_xml

    data = pptx_chart_data(spec)
    chart_space = parse_pptx_xml(ChartXmlWriter(pptx_chart_type(spec.chart_type), data).xml.encode("utf-8"))
    format_chart(Chart(chart_space, None), spec)
    package = document.part.package
    number = _next_chart_number(package)
    workbook = Part(PackURI(f"/word/embeddings/Microsoft_Excel_Sheet{number}.xlsx"), _CT_XLSX, data.xlsx_blob, package)
    chart_part = Part(PackURI(f"/word/charts/chart{number}.xml"), _CT_CHART, b"", package)
    workbook_rid = chart_part.relate_to(workbook, _RT_PACKAGE)
    chart_space.append(
        etree.fromstring(
            f'<c:externalData xmlns:c="{_C_NS}" xmlns:r="{_R_NS}" r:id="{workbook_rid}"><c:autoUpdate val="0"/>'
            "</c:externalData>"
        )
    )
    chart_part._blob = etree.tostring(chart_space, xml_declaration=True, encoding="UTF-8", standalone=True)
    chart_rid = document.part.relate_to(chart_part, _RT_CHART)
    shape_id = _next_docpr_id(document)
    inline = parse_docx_xml(
        '<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        f' xmlns:c="{_C_NS}" xmlns:r="{_R_NS}">'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{shape_id}" name="Chart {shape_id}" descr="{_attr(spec.title or "Chart")}"/>'
        "<wp:cNvGraphicFramePr/>"
        f'<a:graphic><a:graphicData uri="{_C_NS}"><c:chart r:id="{chart_rid}"/></a:graphicData></a:graphic>'
        "</wp:inline></w:drawing>"
    )
    paragraph.add_run()._r.append(inline)


def _attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "CHART_TYPES",
    "ChartSpec",
    "add_docx_chart",
    "add_pptx_chart",
    "chart_spec",
    "format_chart",
    "normalize_chart_type",
    "pptx_chart_data",
    "pptx_chart_type",
]
