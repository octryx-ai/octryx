"""Template assembler for generated Word scripts."""

from __future__ import annotations

from ._office_word_script_template_assets import render_word_script_template_assets
from ._office_word_script_template_core import render_word_script_template_core
from ._office_word_script_template_render import render_word_script_template_render


def render_word_script_template(
    *,
    import_root: str,
    template_path: str,
    output_path: str,
    template_data_literal: str,
    sections_literal: str,
    citation_style: str,
    sources_literal: str,
    include_bibliography: bool,
) -> str:
    return (
        render_word_script_template_core(
            import_root=import_root,
            template_path=template_path,
            output_path=output_path,
            template_data_literal=template_data_literal,
            sections_literal=sections_literal,
            citation_style=citation_style,
            sources_literal=sources_literal,
            include_bibliography=include_bibliography,
        )
        + render_word_script_template_assets()
        + render_word_script_template_render()
    )


__all__ = ["render_word_script_template"]
