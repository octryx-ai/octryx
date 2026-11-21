"""Generated Word document script tool."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._office_generated_base import (
    _GeneratedOfficeScriptToolBase,
    _normalize_bibliography_sources,
    _normalize_word_citation_style,
)
from ._office_generated_run import prepare_generated_output, run_generated_script
from ._office_word_script_build import generate_word_script


class BuildWordTemplateScriptTool(_GeneratedOfficeScriptToolBase):
    name = "build_word_template_script"
    doc_type = "docx"
    description = (
        "Build a Word document from a DOCX/DOTX template by generating and executing an editable Python script. "
        "Supported layout_type values: title_page, toc, section, paragraph, bullets, numbered, table, quote, formula, callout, chart, diagram, process_flow. "
        "Supports optional citation styles: none, ieee, apa, mla, chicago, harvard."
    )

    def _generate_script(
        self,
        *,
        template_path: str,
        output_path: str,
        sections: list[dict[str, Any]],
        template_data: dict[str, Any],
        citation_style: str,
        sources: list[dict[str, Any]],
        include_bibliography: bool,
    ) -> str:
        return generate_word_script(
            template_path=template_path,
            output_path=output_path,
            sections=sections,
            template_data=template_data,
            citation_style=citation_style,
            sources=sources,
            include_bibliography=include_bibliography,
        )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        sections = params.get("sections")
        if not isinstance(sections, list) or not any(isinstance(item, dict) for item in sections):
            return {"error": "sections must be a non-empty list of section objects"}
        template_data = params.get("template_data") if isinstance(params.get("template_data"), dict) else {}
        citation_style = _normalize_word_citation_style(params.get("citation_style"))
        sources = _normalize_bibliography_sources(
            [dict(item) for item in (params.get("sources") or []) if isinstance(item, dict)]
        )
        include_bibliography = bool(params.get("include_bibliography", True))

        refusal, output = await prepare_generated_output(
            context,
            file_path=file_path,
            template_key=str(params.get("template_key") or "").strip(),
            template_path=str(params.get("template_path") or "").strip(),
            doc_type=self.doc_type,
        )
        if output is None:
            return refusal

        usable_sections = [dict(item) for item in sections if isinstance(item, dict)]
        script_content = self._generate_script(
            template_path=str(output.template_resolved) if output.template_resolved else "",
            output_path=str(output.resolved),
            sections=usable_sections,
            template_data=template_data,
            citation_style=citation_style,
            sources=sources,
            include_bibliography=include_bibliography,
        )
        details = {
            "section_count": len(usable_sections),
            "layouts": [str(item.get("layout_type") or "paragraph") for item in usable_sections],
            "citation_style": citation_style,
            "source_count": len(sources),
            "include_bibliography": include_bibliography,
        }
        return await run_generated_script(self, context, output, script_content=script_content, details=details)


__all__ = ["BuildWordTemplateScriptTool"]
