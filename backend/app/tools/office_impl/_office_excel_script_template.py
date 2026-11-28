"""Template renderer for generated Excel scripts."""

from __future__ import annotations

from ._office_excel_script_template_sheets import _excel_script_render_sheets_and_main, _excel_script_sheet_extras


def _excel_script_header(
    *,
    import_root: str,
    template_path: str,
    output_path: str,
    template_data_literal: str,
    sheets_literal: str,
) -> str:
    return f"""\
#!/usr/bin/env python3
\"\"\"Generated Excel build script: openpyxl plus the platform's Office engine helpers.

Edit and re-run with the backend interpreter to adjust content or layout.
\"\"\"
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.path.append({repr(str(import_root))})  # after the libraries: the engine never shadows them

from openpyxl import Workbook, load_workbook  # noqa: E402

from app.services.office.engine import sheets as cells  # noqa: E402
from app.services.office.engine import xlsx_extras as extras  # noqa: E402
from app.services.office.engine.charts import chart_spec  # noqa: E402
from app.services.office.engine.fill import fill_sheets  # noqa: E402
from app.services.office.engine.package import document_bytes, save_document  # noqa: E402
from app.services.office.engine.paths import OfficeEngineError  # noqa: E402

TEMPLATE_PATH = {repr(template_path)}
OUTPUT = Path({repr(output_path)})
TEMPLATE_DATA = json.loads({template_data_literal})
SHEETS = json.loads({sheets_literal})
SPARKLINES: dict[str, list[str]] = {{}}


"""


def _excel_script_workbook_setup() -> str:
    return """\
def open_workbook():
    \"\"\"The template (its {{placeholders}} filled, styles and sparklines kept) or a blank workbook.\"\"\"
    if TEMPLATE_PATH:
        data = document_bytes(TEMPLATE_PATH)
        SPARKLINES.update(extras.read_sparklines(data))
        workbook = load_workbook(io.BytesIO(data))
        workbook.template = False
        report = fill_sheets(workbook, TEMPLATE_DATA)
        print(f"template filled: {report['replaced']} placeholder(s), missing {report['missing']}")
        return workbook
    return Workbook()


WB = open_workbook()


def optional(label: str, action) -> None:
    \"\"\"Run one optional feature; a rejected spec is reported and the build continues.\"\"\"
    try:
        action()
    except OfficeEngineError as exc:
        print(f"{label} skipped: {exc}")


"""


def _excel_script_cell_helpers() -> str:
    return """\
def col_letter(index: int) -> str:
    value = max(1, int(index))
    letters = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def parse_cell(cell: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]+)(\\d+)", str(cell or "").strip())
    if not match:
        return (1, 1)
    letters, row = match.groups()
    col = 0
    for char in letters.upper():
        col = col * 26 + (ord(char) - 64)
    return int(row), col


def cell_ref(row: int, col: int) -> str:
    return f"{col_letter(col)}{row}"


def normalize_cell_payload(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def set_cell(sheet_name: str, cell: str, payload: dict[str, object]) -> None:
    cells.apply_cell_props(WB[sheet_name][cell], payload)


def ensure_sheet(sheet_name: str, index: int) -> str:
    if sheet_name and sheet_name in WB.sheetnames:
        return sheet_name
    if index == 0:
        worksheet = WB.worksheets[0]
        if sheet_name:
            worksheet.title = sheet_name
        return worksheet.title
    return WB.create_sheet(title=sheet_name or f"Sheet{index + 1}").title


def cell_range(start_row: int, start_col: int, end_row: int, end_col: int) -> str:
    return f"{cell_ref(start_row, start_col)}:{cell_ref(end_row, end_col)}"


"""


def _excel_script_table_blocks() -> str:
    return """\
def render_table(sheet_name: str, spec: dict[str, object], *, start_cell: str = "A1") -> tuple[int, int, int, int]:
    start_row, start_col = parse_cell(start_cell)
    title = str(spec.get("title") or "").strip()
    headers = [str(item).strip() for item in (spec.get("headers") or []) if str(item).strip()]
    rows = [row for row in (spec.get("rows") or []) if isinstance(row, list)]
    col_count = max(len(headers), max((len(row) for row in rows), default=0), 1)
    row_cursor = start_row
    if title:
        set_cell(sheet_name, cell_ref(row_cursor, start_col), {"value": title, "font.bold": True, "size": 14})
        row_cursor += 2
    header_row = row_cursor
    if headers:
        for offset, header in enumerate(headers):
            set_cell(
                sheet_name,
                cell_ref(header_row, start_col + offset),
                {"value": header, "font.bold": True, "alignment.horizontal": "center"},
            )
        row_cursor += 1
    for row in rows:
        for offset, raw_cell in enumerate(row):
            payload = normalize_cell_payload(raw_cell)
            set_cell(sheet_name, cell_ref(row_cursor, start_col + offset), payload)
        row_cursor += 1
    formulas = spec.get("formulas") or {}
    if isinstance(formulas, dict):
        for cell, formula in formulas.items():
            set_cell(sheet_name, str(cell), {"formula": formula})
    return header_row, row_cursor - 1, start_col, start_col + col_count - 1


def render_kpi_summary(sheet_name: str, spec: dict[str, object]) -> None:
    title = str(spec.get("title") or "").strip()
    if title:
        set_cell(sheet_name, "A1", {"value": title, "font.bold": True, "size": 14})
    kpis = [item for item in (spec.get("kpis") or []) if isinstance(item, dict)]
    row_cursor = 3
    for item in kpis:
        label = str(item.get("label") or "").strip()
        value_payload = normalize_cell_payload(item.get("value"))
        for prop_name in ("formula", "numFmt", "fill", "font.color"):
            if prop_name in item:
                value_payload[prop_name] = item[prop_name]
        if label:
            set_cell(sheet_name, f"A{row_cursor}", {"value": label, "font.bold": True})
        set_cell(sheet_name, f"B{row_cursor}", value_payload)
        row_cursor += 1


"""


def render_excel_script_template(
    *,
    import_root: str,
    template_path: str,
    output_path: str,
    template_data_literal: str,
    sheets_literal: str,
) -> str:
    return (
        _excel_script_header(
            import_root=import_root,
            template_path=template_path,
            output_path=output_path,
            template_data_literal=template_data_literal,
            sheets_literal=sheets_literal,
        )
        + _excel_script_workbook_setup()
        + _excel_script_cell_helpers()
        + _excel_script_table_blocks()
        + _excel_script_sheet_extras()
        + _excel_script_render_sheets_and_main()
    )


__all__ = ["render_excel_script_template"]
