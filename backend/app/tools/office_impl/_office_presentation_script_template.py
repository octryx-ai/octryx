"""Template renderer for generated PowerPoint scripts (python-pptx plus the Office engine helpers)."""

from __future__ import annotations


def _presentation_script_header(
    *,
    import_root: str,
    source_potx: str,
    output_pptx: str,
    orig_slides: int,
    clone_order_repr: str,
) -> str:
    return f'''\
#!/usr/bin/env python3
"""Generated presentation build script: python-pptx plus the platform's Office engine helpers.

Edit and re-run with the backend interpreter to adjust content or layout.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.append({repr(str(import_root))})  # after the libraries: the engine never shadows them

from pptx import Presentation  # noqa: E402

from app.services.office.engine import slides as deck  # noqa: E402
from app.services.office.engine import slides_build as build  # noqa: E402
from app.services.office.engine.package import document_bytes, save_document  # noqa: E402
from app.services.office.engine.paths import OfficeEngineError, parse_path  # noqa: E402

TEMPLATE = Path({repr(source_potx)})
DECK = Path({repr(output_pptx)})
ORIG_SLIDES = {orig_slides}

CLONE_ORDER = {clone_order_repr}

PRS = None


'''


def _presentation_script_text_ops() -> str:
    return '''\
def set_text(ops: list[dict], path: str, text: str, size: str | None = None) -> None:
    props = {"text": text}
    if size:
        props["size"] = size
    ops.append({"path": path, "props": props})


def apply_ops(label: str, ops: list[dict]) -> None:
    """Set each addressed shape's text; a path the template does not have is reported and skipped."""
    applied = 0
    for op in ops:
        try:
            deck.set_props(deck.resolve(PRS, parse_path(op["path"])), op["props"])
            applied += 1
        except OfficeEngineError as exc:
            print(f"{label}: {op['path']} skipped ({exc})")
    print(f"{label}: {applied}/{len(ops)} applied")


def slide(slide_index: int):
    return PRS.slides[slide_index - 1]


def add_slide_shape(slide_index: int, props: dict[str, object]) -> None:
    build.add_shape(slide(slide_index), {"preset": "rect", **props})


'''


def _presentation_script_slide_visuals() -> str:
    return """\
def add_slide_connector(slide_index: int, props: dict[str, object]) -> None:
    build.add_connector(slide(slide_index), props)


def add_slide_chart(slide_index: int, chart_spec: dict[str, object]) -> None:
    if not isinstance(chart_spec, dict):
        return
    try:
        build.add_chart(slide(slide_index), chart_spec)
    except OfficeEngineError as exc:
        print(f"chart on slide {slide_index} skipped ({exc})")


def add_slide_table(slide_index: int, table_spec: dict[str, object]) -> None:
    if not isinstance(table_spec, dict):
        return
    try:
        build.add_table(slide(slide_index), {"x": "2.0cm", "y": "4.6cm", "width": "20.5cm", **table_spec})
    except OfficeEngineError as exc:
        print(f"table on slide {slide_index} skipped ({exc})")


"""


def _presentation_script_render_process_flow() -> str:
    return """\
def render_process_flow(slide_index: int, steps: list[dict[str, object]]) -> None:
    flow_steps = [step for step in steps if isinstance(step, dict)]
    if not flow_steps:
        return
    step_count = min(len(flow_steps), 4)
    gap_cm = 0.5
    total_width = 21.0
    box_width = (total_width - (gap_cm * (step_count - 1))) / step_count
    box_height = 3.0
    origin_x = 1.4
    origin_y = 6.1
    colors = ["0F4C81", "1F7A8C", "3A7D44", "8C5E34"]
    for index in range(step_count):
        step = flow_steps[index]
        x = origin_x + index * (box_width + gap_cm)
        text = str(step.get("title") or "").strip()
        body = str(step.get("body") or "").strip()
        if body:
            text = f"{text}\\n{body}"
        add_slide_shape(
            slide_index,
            {
                "preset": "roundRect",
                "text": text,
                "x": f"{x:.2f}cm",
                "y": f"{origin_y:.2f}cm",
                "width": f"{box_width:.2f}cm",
                "height": f"{box_height:.2f}cm",
                "fill": colors[index % len(colors)],
                "line": colors[index % len(colors)],
                "color": "FFFFFF",
                "bold": "true",
                "size": "16",
                "align": "center",
                "valign": "center",
                "margin": "0.18cm",
            },
        )
        if index >= step_count - 1:
            continue
        connector_x = x + box_width
        add_slide_connector(
            slide_index,
            {
                "x": f"{connector_x:.2f}cm",
                "y": f"{origin_y + 1.5:.2f}cm",
                "width": f"{gap_cm:.2f}cm",
                "height": "0cm",
                "line": "4B5563",
                "lineWidth": "2pt",
                "tailEnd": "triangle",
            },
        )


"""


def _presentation_script_builders_and_main(*, text_ops_body: str, visual_ops_body: str) -> str:
    return f"""\
def build_text_ops() -> list[dict]:
{text_ops_body}


def build_visuals() -> None:
{visual_ops_body}


def main() -> None:
    global PRS
    if not TEMPLATE.exists():
        sys.exit(f"Template not found: {{TEMPLATE}}")

    print("\\n[1/4] Opening the template as a presentation")
    PRS = Presentation(io.BytesIO(document_bytes(TEMPLATE)))
    originals = list(PRS.slides)[:ORIG_SLIDES]

    print("\\n[2/4] Cloning reference slides")
    for slide_num in CLONE_ORDER:
        if not 1 <= slide_num <= len(originals):
            sys.exit(f"Template has {{len(originals)}} example slides; slide {{slide_num}} is not one of them")
        build.clone_slide(PRS, originals[slide_num - 1])

    print("\\n[3/4] Removing original template slides")
    for original in originals:
        deck.remove_slide(PRS, original)

    print("\\n[4/4] Applying content")
    apply_ops("content", build_text_ops())
    build_visuals()

    save_document(PRS, DECK)
    print(f"\\nDone. Built deck: {{DECK}}")


if __name__ == "__main__":
    main()
"""


def render_presentation_script_template(
    *,
    import_root: str,
    source_potx: str,
    output_pptx: str,
    orig_slides: int,
    clone_order_repr: str,
    text_ops_body: str,
    visual_ops_body: str,
) -> str:
    return (
        _presentation_script_header(
            import_root=import_root,
            source_potx=source_potx,
            output_pptx=output_pptx,
            orig_slides=orig_slides,
            clone_order_repr=clone_order_repr,
        )
        + _presentation_script_text_ops()
        + _presentation_script_slide_visuals()
        + _presentation_script_render_process_flow()
        + _presentation_script_builders_and_main(text_ops_body=text_ops_body, visual_ops_body=visual_ops_body)
    )


__all__ = ["render_presentation_script_template"]
