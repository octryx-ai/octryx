"""Script generation helpers for generated PowerPoint presentations."""

from __future__ import annotations

from typing import Any

from ...services.office.engine import IMPORT_ROOT
from ._office_presentation_script_template import render_presentation_script_template
from ._office_presentation_script_text import build_presentation_text_ops_code


def build_presentation_visual_ops_code(slides: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, slide in enumerate(slides, start=1):
        layout = str(slide.get("layout_type") or "").strip()
        if layout == "table":
            table = dict(slide.get("table") or {})
            lines.append(f"    add_slide_table({idx}, {repr(table)})")
            insight = str(slide.get("insight") or "").strip()
            if insight:
                lines.append(
                    "    add_slide_shape("
                    f"{idx}, "
                    "{'text': "
                    f"{repr(insight)}, "
                    "'x': '2.0cm', 'y': '14.2cm', 'width': '20.8cm', 'height': '1.2cm', "
                    "'fill': 'F5F7FA', 'line': 'CBD2D9', 'color': '1F2933', 'size': '12', 'margin': '0.12cm'}"
                    ")"
                )
        elif layout == "chart":
            chart = dict(slide.get("chart") or {})
            lines.append(f"    add_slide_chart({idx}, {repr(chart)})")
            insight = str(slide.get("insight") or "").strip()
            if insight:
                lines.append(
                    "    add_slide_shape("
                    f"{idx}, "
                    "{'text': "
                    f"{repr(insight)}, "
                    "'x': '2.0cm', 'y': '14.2cm', 'width': '20.8cm', 'height': '1.2cm', "
                    "'fill': 'F3F6FA', 'line': 'D9E2EC', 'color': '1F2933', 'size': '12', 'margin': '0.12cm'}"
                    ")"
                )
        elif layout == "process_flow":
            steps = slide.get("steps") if isinstance(slide.get("steps"), list) else []
            lines.append(f"    render_process_flow({idx}, {repr(steps)})")
            insight = str(slide.get("insight") or "").strip()
            if insight:
                lines.append(
                    "    add_slide_shape("
                    f"{idx}, "
                    "{'text': "
                    f"{repr(insight)}, "
                    "'x': '2.0cm', 'y': '13.9cm', 'width': '20.8cm', 'height': '1.3cm', "
                    "'fill': 'F7F4EA', 'line': 'D9C8A9', 'color': '5B4636', 'size': '12', 'margin': '0.14cm'}"
                    ")"
                )
    return "\n".join(lines) if lines else "    return"


def generate_presentation_script(
    *,
    source_potx: str,
    output_pptx: str,
    orig_slides: int,
    clone_order: list[int],
    slides: list[dict[str, Any]],
) -> str:
    text_ops_body = build_presentation_text_ops_code(slides)
    visual_ops_body = build_presentation_visual_ops_code(slides)
    return render_presentation_script_template(
        import_root=str(IMPORT_ROOT),
        source_potx=source_potx,
        output_pptx=output_pptx,
        orig_slides=orig_slides,
        clone_order_repr=repr(clone_order),
        text_ops_body=text_ops_body,
        visual_ops_body=visual_ops_body,
    )


__all__ = [
    "build_presentation_visual_ops_code",
    "generate_presentation_script",
]
