"""Basic office document manipulation tool classes (in-process Office engine)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.office.documents import office_document_type
from ...services.office.engine import api as office_engine
from ...services.office.engine.package import is_template
from ...services.office.render import render_check
from ...services.office.slide_checks import slide_gate_check
from ._office_core_helpers import (
    _artifact_for_path,
    _engine,
    _resolve_path,
    _resolve_template_for_output,
    _template_path_refusal,
    _workspace_root,
)


def _with_artifact(result: dict[str, Any], context: ToolContext, resolved: Path) -> dict[str, Any]:
    if resolved.exists():
        result["artifacts"] = [_artifact_for_path(context, resolved)]
    return result


class CreateOfficeDocumentTool:
    name = "create_office_document"
    description = (
        "Create a new Office document (.docx, .xlsx, or .pptx) inside the workspace. "
        "When available, the active corporate identity default template is used for PPTX, DOCX, and XLSX, "
        'for example {"file_path":"deck.pptx","doc_type":"pptx"}.'
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        requested_type = str(params.get("doc_type") or "").strip().lower()
        template_key = str(params.get("template_key") or "").strip()
        template_path = str(params.get("template_path") or "").strip()
        template_data = params.get("template_data") if isinstance(params.get("template_data"), dict) else {}
        refusal = _template_path_refusal(context, template_path)
        if refusal:
            return refusal
        resolved = _resolve_path(context, file_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        doc_type = requested_type or office_document_type(resolved)
        template_resolved: Path | None = None
        template_entry: dict[str, Any] | None = None
        try:
            # Explicit key/path, else the corporate-identity or library default for the type.
            template_resolved, template_entry = await _resolve_template_for_output(
                context,
                template_key=template_key,
                template_path=template_path,
                doc_type=doc_type,
            )
        except FileNotFoundError:
            if template_key or template_path:
                raise
        if template_resolved is not None:
            result = await _engine(office_engine.merge, template_resolved, resolved, template_data)
            if result.get("success"):
                result["normalized_document_type"] = is_template(template_resolved)
            result["template_path"] = str(template_resolved)
            if template_entry:
                result["template_key"] = str(template_entry.get("key") or "")
        else:
            result = await _engine(office_engine.create, resolved, requested_type)
        result["file_path"] = str(resolved)
        result["relative_path"] = str(resolved.relative_to(_workspace_root(context)))
        return _with_artifact(result, context, resolved)


class ReadOfficeDocumentTool:
    name = "read_office_document"
    description = (
        "Read a Word, Excel, or PowerPoint document in text, outline, annotated, stats, issues, html, "
        "or forms (Word) mode."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        mode = str(params.get("view") or "text").strip().lower() or "text"
        if not file_path:
            return {"error": "file_path is required"}
        resolved = _resolve_path(context, file_path)
        return await _engine(
            office_engine.view,
            resolved,
            mode,
            start=params.get("start"),
            end=params.get("end"),
            max_lines=params.get("max_lines"),
        )


class GetOfficeDocumentInfoTool:
    name = "get_office_document_info"
    description = "Get Office document stats such as paragraphs, words, sheets, or slides."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        return await _engine(office_engine.view, _resolve_path(context, file_path), "stats")


class ValidateOfficeDocumentTool:
    name = "validate_office_document"
    description = (
        "Validate an Office document: it must open, and its issues (formula errors, broken references, unfilled "
        "placeholders, empty slides, shapes off the slide, missing alt text) are listed. "
        "Set render=true to also render it once in the network-isolated renderer (slower; off by default)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        resolved = _resolve_path(context, file_path)
        result = await _engine(
            office_engine.view,
            resolved,
            "issues",
            issue_type=str(params.get("issue_type") or "").strip(),
            limit=params.get("limit"),
        )
        if result.get("success"):
            if resolved.suffix.lower() == ".pptx":
                result["slide_gate"] = await asyncio.to_thread(slide_gate_check, resolved, resolved)
            if params.get("render") is True:
                result["render"] = await render_check(resolved)
        return result


class GetOfficeElementTool:
    name = "get_office_element"
    description = (
        "Read one Office document element by path with controlled depth, e.g. /body/p[3], "
        "/body/tbl[1]/tr[2]/tc[1], /slide[2]/shape[1], /slide[2]/table[1], /Sheet1/B4, /Sheet1/A1:C9."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        element_path = str(params.get("path") or "").strip()
        depth = int(params.get("depth") or 2)
        if not file_path or not element_path:
            return {"error": "file_path and path are required"}
        resolved = _resolve_path(context, file_path)
        return await _engine(office_engine.get, resolved, element_path, max(1, min(depth, 6)))


class QueryOfficeElementsTool:
    name = "query_office_elements"
    description = (
        "Query multiple Office document elements by selector: a type with optional filters, e.g. paragraph, "
        "p[style=Heading1], shape[text~=Revenue], cell:contains(total), slide[layout=Title Slide]."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        selector = str(params.get("selector") or "").strip()
        if not file_path or not selector:
            return {"error": "file_path and selector are required"}
        return await _engine(office_engine.query, _resolve_path(context, file_path), selector)


class SetOfficePropertyTool:
    name = "set_office_property"
    description = "Set one or more Office document properties (text, style, font, color, fill, geometry, value) on a selected node."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        target_path = str(params.get("path") or "").strip()
        properties = params.get("properties") or {}
        if not file_path or not target_path:
            return {"error": "file_path and path are required"}
        if not isinstance(properties, dict) or not properties:
            return {"error": "properties object is required"}
        resolved = _resolve_path(context, file_path)
        result = await _engine(office_engine.set_properties, resolved, target_path, properties)
        return _with_artifact(result, context, resolved)


class AddOfficeElementTool:
    name = "add_office_element"
    description = (
        "Add an element such as a paragraph, heading, table, picture, chart, slide, shape, connector, sheet, "
        "validation or conditional format to an Office document. "
        "For PowerPoint slides, use `from_path` to clone a template example slide (preferred — preserves all layout shapes): "
        '{"element_type":"slide","parent_path":"/","from_path":"/slide[11]"}. '
        "Alternatively, use `properties` with a layout name: "
        '{"element_type":"slide","parent_path":"/","properties":{"layout":"Title and Bulletpoints"}}. '
        "`index` (1-based) inserts at a position instead of appending."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        parent_path = str(params.get("parent_path") or "").strip()
        element_type = str(params.get("element_type") or "").strip()
        from_path = str(params.get("from_path") or "").strip()
        properties = dict(params.get("properties") or {}) if isinstance(params.get("properties"), dict) else {}
        if not file_path or not parent_path or not element_type:
            return {"error": "file_path, parent_path, and element_type are required"}
        resolved = _resolve_path(context, file_path)
        if element_type.strip().lower() == "picture" and str(properties.get("path") or "").strip():
            # Pictures come from the workspace only.
            properties["path"] = str(_resolve_path(context, str(properties["path"])))
        index = params.get("index")
        result = await _engine(
            office_engine.add,
            resolved,
            parent_path,
            element_type,
            properties,
            from_path=from_path,
            index=int(index) if index is not None else None,
        )
        return _with_artifact(result, context, resolved)


class RemoveOfficeElementTool:
    name = "remove_office_element"
    description = "Remove an element from an Office document."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        target_path = str(params.get("path") or "").strip()
        if not file_path or not target_path:
            return {"error": "file_path and path are required"}
        resolved = _resolve_path(context, file_path)
        result = await _engine(office_engine.remove, resolved, target_path)
        return _with_artifact(result, context, resolved)


class FillOfficeTemplateTool:
    name = "fill_office_template"
    description = (
        "Fill a DOCX, XLSX, or PPTX template's {{placeholders}} with JSON data, keeping the template's styling. "
        "When available, the active corporate identity default template is used when no explicit template is provided."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        template_path = str(params.get("template_path") or "").strip()
        template_key = str(params.get("template_key") or "").strip()
        output_path = str(params.get("output_path") or "").strip()
        data = params.get("data")
        if not output_path:
            return {"error": "output_path is required"}
        if data is None:
            return {"error": "data is required"}
        if not isinstance(data, dict):
            return {"error": "data must be an object"}
        refusal = _template_path_refusal(context, template_path)
        if refusal:
            return refusal
        output = _resolve_path(context, output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        doc_type = office_document_type(output)
        template, template_entry = await _resolve_template_for_output(
            context,
            template_key=template_key,
            template_path=template_path,
            doc_type=doc_type,
        )
        result = await _engine(office_engine.merge, template, output, data)
        if result.get("success"):
            result["normalized_document_type"] = is_template(template)
        if template_entry:
            result["template_key"] = str(template_entry.get("key") or "")
        result["template_path"] = str(template)
        return _with_artifact(result, context, output)


