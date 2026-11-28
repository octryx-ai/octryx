"""Generated PowerPoint presentation script tool."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._office_core_helpers import _resolve_path, _resolve_presentation_template_with_fallback
from ._office_generated_base import office_validation
from ._office_presentation_script_build import generate_presentation_script
from ._office_presentation_script_run import DeckTarget, build_deck, deck_result, parse_slides_param, source_potx_for
from ._office_presentation_script_text import (
    PRESENTATION_SOURCE_INDEX,
    build_presentation_text_ops_code,
    quality_checked_presentation_slides,
)


class BuildPresentationScriptTool:
    _SOURCE_INDEX = PRESENTATION_SOURCE_INDEX

    def _build_text_ops_code(self, slide_specs: list[dict[str, Any]]) -> str:
        return build_presentation_text_ops_code(slide_specs)

    def _generate_script(
        self,
        source_potx: str,
        output_pptx: str,
        orig_slides: int,
        clone_order: list[int],
        slides: list[dict[str, Any]],
    ) -> str:
        return generate_presentation_script(
            source_potx=source_potx,
            output_pptx=output_pptx,
            orig_slides=orig_slides,
            clone_order=clone_order,
            slides=slides,
        )

    name = "build_presentation_script"
    description = (
        "Builds a high-quality PowerPoint presentation using the full corporate template. "
        "Generates an editable Python script and executes it. "
        "Supported layout_type values: 'title', 'agenda', 'section', 'bullets', "
        "'two_columns', 'three_columns', 'four_columns', 'quote', 'table', 'chart', 'process_flow'. "
        'Example: {"file_path": "deck.pptx", "slides": ['
        '{"layout_type": "title", "title": "My Title", "subtitle": "Subtitle", "footer": "Author · 2026"}, '
        '{"layout_type": "agenda", "title": "Agenda", "subtitle": "Today\'s Topics", "items": ["Topic 1", "Topic 2"]}, '
        '{"layout_type": "section", "title": "Section 1", "subtitle": "Overview"}, '
        '{"layout_type": "table", "title": "KPIs", "headers": ["Metric", "Value"], "rows": [["Cost", "-12%"], ["Speed", "+18%"]]}, '
        '{"layout_type": "chart", "title": "Trend", "chart": {"chart_type": "line", "categories": ["Q1", "Q2"], "series": [{"name": "Revenue", "values": [12, 16]}]}}, '
        '{"layout_type": "process_flow", "title": "Workflow", "steps": [{"title": "Input"}, {"title": "Review"}, {"title": "Release"}]}, '
        '{"layout_type": "four_columns", "title": "Key Areas", "columns": [{"label": "Speed", "body": "Fast\\nReliable"}, ...]}, '
        '{"layout_type": "quote", "quote": "Great quote here", "author": "Name"}, '
        '{"layout_type": "title", "title": "Thank You", "subtitle": "Contact info"}]}'
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"error": "file_path is required"}
        if context.db is None:
            return {"error": "database session is required for build_presentation_script"}
        slides_error, slides = parse_slides_param(params)
        if slides_error:
            return slides_error
        source_slide_count = len([slide for slide in slides if isinstance(slide, dict)])
        if source_slide_count == 0:
            return {"error": "slides must contain slide objects"}

        resolved = _resolve_path(context, file_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)

        # The script clones the corporate template's indexed example slides (PRESENTATION_SOURCE_INDEX),
        # so only a corporate identity profile can serve it; without one the state is explicit.
        resolved_template = await _resolve_presentation_template_with_fallback(context.db)
        if resolved_template is None:
            return _presentation_template_unconfigured()
        template_path, detail, template_source = resolved_template
        target = DeckTarget(
            resolved=resolved,
            source_potx=source_potx_for(detail, template_path),
            orig_slides=int(detail.get("source_slide_count") or 110),
        )

        checked_slides = quality_checked_presentation_slides(slides, aggressive=False)
        if not checked_slides:
            return {"error": "slides did not contain usable content"}
        build_error, build = await build_deck(self._generate_script, target, checked_slides)
        if build is None:
            return build_error
        validation = await office_validation(resolved)
        return deck_result(
            context,
            target,
            build,
            detail=detail,
            template_source=template_source,
            source_slide_count=source_slide_count,
            validation=validation,
        )


def _presentation_template_unconfigured() -> dict[str, Any]:
    from ...services.office.presentation_fallback import PRESENTATION_TEMPLATE_UNCONFIGURED, needs_configuration
    from ...services.prompt_catalog import render_prompt

    return needs_configuration(
        PRESENTATION_TEMPLATE_UNCONFIGURED, render_prompt("office.presentation.template_unconfigured")
    )
