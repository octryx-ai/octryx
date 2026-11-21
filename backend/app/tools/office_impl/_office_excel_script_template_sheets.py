"""Sheet extras, sheet rendering and entry point of generated Excel scripts."""

from __future__ import annotations


def _excel_script_sheet_extras() -> str:
    return """\
def render_matrix(sheet_name: str, spec: dict[str, object]) -> None:
    title = str(spec.get("title") or "").strip()
    if title:
        set_cell(sheet_name, "A1", {"value": title, "font.bold": True, "size": 14})
    column_headers = [str(item).strip() for item in (spec.get("column_headers") or []) if str(item).strip()]
    row_headers = [str(item).strip() for item in (spec.get("row_headers") or []) if str(item).strip()]
    values = [row for row in (spec.get("values") or []) if isinstance(row, list)]
    base_row = 3
    if column_headers:
        for offset, header in enumerate(column_headers, start=2):
            set_cell(sheet_name, cell_ref(base_row, offset), {"value": header, "font.bold": True})
    for row_offset, row_header in enumerate(row_headers, start=1):
        set_cell(sheet_name, cell_ref(base_row + row_offset, 1), {"value": row_header, "font.bold": True})
        row_values = values[row_offset - 1] if row_offset - 1 < len(values) else []
        for col_offset, raw_value in enumerate(row_values, start=2):
            set_cell(sheet_name, cell_ref(base_row + row_offset, col_offset), normalize_cell_payload(raw_value))


def add_chart(sheet_name: str, chart: dict[str, object]) -> None:
    if not str(chart.get("chart_type") or chart.get("type") or "").strip():
        return
    optional("chart", lambda: extras.add_chart(WB, WB[sheet_name], chart_spec(chart), chart))


def add_sparkline(sheet_name: str, sparkline: dict[str, object]) -> None:
    if not isinstance(sparkline, dict):
        return
    optional("sparkline", lambda: SPARKLINES.setdefault(sheet_name, []).append(extras.sparkline_group(sheet_name, sparkline)))


def add_validation(sheet_name: str, validation: dict[str, object]) -> None:
    if isinstance(validation, dict):
        optional("validation", lambda: extras.add_validation(WB[sheet_name], validation))


def add_conditional_format(sheet_name: str, conditional_format: dict[str, object]) -> None:
    if isinstance(conditional_format, dict):
        optional("conditional format", lambda: extras.add_conditional_format(WB[sheet_name], conditional_format))


def add_autofilter(sheet_name: str, filter_range: str) -> None:
    if str(filter_range or "").strip():
        extras.set_autofilter(WB[sheet_name], filter_range)


def add_pivot_table(sheet_name: str, pivot: dict[str, object]) -> None:
    if not isinstance(pivot, dict) or not str(pivot.get("source") or "").strip():
        return

    def build() -> None:
        details = extras.pivot_summary(WB, WB[sheet_name], pivot)
        print(f"pivot on {sheet_name}: {details}")

    optional("pivot table", build)


"""


def _excel_script_render_sheets_and_main() -> str:
    return """\
def render_sheets() -> None:
    for index, raw_sheet in enumerate(SHEETS):
        if not isinstance(raw_sheet, dict):
            continue
        sheet_name = ensure_sheet(str(raw_sheet.get("name") or "").strip(), index)
        layout = str(raw_sheet.get("layout_type") or "table").strip().lower()
        table_bounds: tuple[int, int, int, int] | None = None
        if layout == "kpi_summary":
            render_kpi_summary(sheet_name, raw_sheet)
        elif layout == "matrix":
            render_matrix(sheet_name, raw_sheet)
        elif layout == "pivot_table":
            table_bounds = render_table(sheet_name, raw_sheet, start_cell=str(raw_sheet.get("start_cell") or "A1"))
            pivot_spec = dict(raw_sheet.get("pivot_table") or {})
            if table_bounds and not str(pivot_spec.get("source") or "").strip():
                start_row, end_row, start_col, end_col = table_bounds
                pivot_spec["source"] = f"{sheet_name}!{cell_range(start_row, start_col, end_row, end_col)}"
            add_pivot_table(sheet_name, pivot_spec)
        else:
            table_bounds = render_table(sheet_name, raw_sheet, start_cell=str(raw_sheet.get("start_cell") or "A1"))
        charts = [dict(item) for item in (raw_sheet.get("charts") or []) if isinstance(item, dict)]
        if layout == "chart" and isinstance(raw_sheet.get("chart"), dict) and raw_sheet.get("chart"):
            charts.insert(0, dict(raw_sheet["chart"]))
        for chart in charts:
            has_data = str(chart.get("data_range") or chart.get("range") or "").strip() or chart.get("series")
            if table_bounds and not has_data:
                start_row, end_row, start_col, end_col = table_bounds
                chart["data_range"] = f"{sheet_name}!{cell_range(start_row, start_col, end_row, end_col)}"
            add_chart(sheet_name, chart)
        for sparkline in (raw_sheet.get("sparklines") or []):
            add_sparkline(sheet_name, sparkline)
        for validation_spec in (raw_sheet.get("validations") or []):
            if isinstance(validation_spec, dict):
                add_validation(sheet_name, validation_spec)
        for cf_spec in (raw_sheet.get("conditional_formats") or []):
            if isinstance(cf_spec, dict):
                add_conditional_format(sheet_name, cf_spec)
        for pivot_spec in (raw_sheet.get("pivot_tables") or []):
            if isinstance(pivot_spec, dict):
                add_pivot_table(sheet_name, pivot_spec)
        auto_filter_range = str(raw_sheet.get("auto_filter_range") or "").strip()
        if auto_filter_range:
            add_autofilter(sheet_name, auto_filter_range)


def main() -> None:
    render_sheets()
    save_document(WB, OUTPUT)
    extras.write_sparklines(OUTPUT, SPARKLINES)
    print(f"Done. Built workbook: {OUTPUT}")


if __name__ == "__main__":
    main()
"""


__all__ = ["_excel_script_render_sheets_and_main", "_excel_script_sheet_extras"]
