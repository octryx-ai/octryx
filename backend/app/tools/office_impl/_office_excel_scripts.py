"""Generated Excel workbook script tool and Excel helper tools."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...services.office.engine import api as office_engine
from ._office_core_helpers import _artifact_for_path, _engine, _resolve_path
from ._office_excel_script_build import generate_excel_script
from ._office_generated_base import _GeneratedOfficeScriptToolBase
from ._office_generated_run import prepare_generated_output, run_generated_script


class BuildExcelTemplateScriptTool(_GeneratedOfficeScriptToolBase):
    name = "build_excel_template_script"
    doc_type = "xlsx"
    description = (
        "Build an Excel workbook from an XLSX/XLTX template by generating and executing an editable Python script. "
        "Supported layout_type values: table, kpi_summary, matrix, chart, sparkline, pivot_table. "
        "Also supports conditional_formats, validations, auto_filter_range, and pivot_tables per sheet."
    )

    def _generate_script(
        self,
        *,
        template_path: str,
        output_path: str,
        sheets: list[dict[str, Any]],
        template_data: dict[str, Any],
    ) -> str:
        return generate_excel_script(
            template_path=template_path,
            output_path=output_path,
            sheets=sheets,
            template_data=template_data,
        )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        sheets = params.get("sheets")
        if not isinstance(sheets, list) or not any(isinstance(item, dict) for item in sheets):
            return {"error": "sheets must be a non-empty list of sheet objects"}
        template_data = params.get("template_data") if isinstance(params.get("template_data"), dict) else {}

        refusal, output = await prepare_generated_output(
            context,
            file_path=file_path,
            template_key=str(params.get("template_key") or "").strip(),
            template_path=str(params.get("template_path") or "").strip(),
            doc_type=self.doc_type,
        )
        if output is None:
            return refusal

        usable_sheets = [dict(item) for item in sheets if isinstance(item, dict)]
        script_content = self._generate_script(
            template_path=str(output.template_resolved) if output.template_resolved else "",
            output_path=str(output.resolved),
            sheets=usable_sheets,
            template_data=template_data,
        )
        details = {
            "sheet_count": len(usable_sheets),
            "sheet_names": [str(item.get("name") or f"Sheet{idx + 1}") for idx, item in enumerate(usable_sheets)],
        }
        return await run_generated_script(self, context, output, script_content=script_content, details=details)


class ReadExcelCellTool:
    name = "read_excel_cell"
    description = "Read one Excel cell or range, e.g. /Sheet1/B4, /Sheet1/A1:C9 or Sheet1!B4."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        cell_path = str(params.get("path") or "").strip()
        if not file_path or not cell_path:
            return {"error": "file_path and path are required"}
        return await _engine(office_engine.get, _resolve_path(context, file_path), cell_path, 1)


class SetExcelCellTool:
    name = "set_excel_cell"
    description = (
        "Set one Excel cell value. The value is stored as data (a leading = stays text); write a formula with "
        'set_office_property and {"formula": "=SUM(B2:B9)"}.'
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        cell_path = str(params.get("path") or "").strip()
        value = params.get("value")
        if not file_path or not cell_path:
            return {"error": "file_path and path are required"}
        resolved = _resolve_path(context, file_path)
        result = await _engine(office_engine.set_properties, resolved, cell_path, {"value": value})
        if resolved.exists():
            result["artifacts"] = [_artifact_for_path(context, resolved)]
        return result


class CreateExcelChartTool:
    name = "create_excel_chart"
    description = (
        "Create a native chart in an Excel workbook from a data range (header row + category column), e.g. "
        '{"parent_path":"/Sheet1","chart_type":"column","properties":{"dataRange":"Sheet1!A1:C5","title":"Revenue"}}.'
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        parent_path = str(params.get("parent_path") or "").strip()
        chart_type = str(params.get("chart_type") or "").strip()
        if not file_path or not chart_type:
            return {"error": "file_path and chart_type are required"}
        properties = dict(params.get("properties") or {})
        properties.setdefault("chart_type", chart_type)
        resolved = _resolve_path(context, file_path)
        if not parent_path or parent_path == "/":
            first_sheet = await _engine(office_engine.get, resolved, "/", 1)
            sheets = (first_sheet.get("data") or {}).get("sheets") or []
            if not sheets:
                return first_sheet if first_sheet.get("error") else {"error": "workbook has no sheet"}
            parent_path = f"/{sheets[0]}"
        result = await _engine(office_engine.add, resolved, parent_path, "chart", properties)
        if resolved.exists():
            result["artifacts"] = [_artifact_for_path(context, resolved)]
        return result


class GetPresentationHtmlTool:
    name = "get_presentation_html"
    description = "Render a PowerPoint presentation as HTML for preview or export."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        return await _engine(office_engine.view, _resolve_path(context, file_path), "html")


__all__ = [
    "BuildExcelTemplateScriptTool",
    "CreateExcelChartTool",
    "GetPresentationHtmlTool",
    "ReadExcelCellTool",
    "SetExcelCellTool",
]
