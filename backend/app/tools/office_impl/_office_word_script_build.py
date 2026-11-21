"""Script generation helpers for generated Word documents."""

from __future__ import annotations

from typing import Any

from ...services.office.engine import IMPORT_ROOT
from ._office_generated_base import _json_script_literal
from ._office_word_script_template import render_word_script_template


def generate_word_script(
    *,
    template_path: str,
    output_path: str,
    sections: list[dict[str, Any]],
    template_data: dict[str, Any],
    citation_style: str,
    sources: list[dict[str, Any]],
    include_bibliography: bool,
) -> str:
    return render_word_script_template(
        import_root=str(IMPORT_ROOT),
        template_path=template_path,
        output_path=output_path,
        template_data_literal=_json_script_literal(template_data),
        sections_literal=_json_script_literal(sections),
        citation_style=citation_style,
        sources_literal=_json_script_literal(sources),
        include_bibliography=include_bibliography,
    )


__all__ = ["generate_word_script"]
