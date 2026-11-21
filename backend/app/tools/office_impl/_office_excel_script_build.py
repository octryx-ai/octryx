"""Script generation helpers for generated Excel workbooks."""

from __future__ import annotations

from typing import Any

from ...services.office.engine import IMPORT_ROOT
from ._office_excel_script_template import render_excel_script_template
from ._office_generated_base import _json_script_literal


def generate_excel_script(
    *,
    template_path: str,
    output_path: str,
    sheets: list[dict[str, Any]],
    template_data: dict[str, Any],
) -> str:
    return render_excel_script_template(
        import_root=str(IMPORT_ROOT),
        template_path=template_path,
        output_path=output_path,
        template_data_literal=_json_script_literal(template_data),
        sheets_literal=_json_script_literal(sheets),
    )


__all__ = ["generate_excel_script"]
