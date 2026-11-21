"""Word documents (python-docx): styles, paragraph and run properties, page breaks and charts."""

from __future__ import annotations

from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

from .charts import add_docx_chart, chart_spec
from .paths import INVALID_REQUEST, OfficeEngineError, flag, hex_color, length_emu, points

ALIGNMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "centre": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def find_style(document: Any, requested: Any) -> Any:
    wanted = str(requested or "").strip()
    normalized = wanted.replace(" ", "").lower()
    for style in document.styles:
        if normalized in {str(style.name or "").replace(" ", "").lower(), str(style.style_id or "").lower()}:
            return style
    raise OfficeEngineError(INVALID_REQUEST, f"unknown style {wanted!r}")


def apply_run_props(run: Any, props: dict[str, Any]) -> None:
    font = run.font
    for key, value in props.items():
        name = key.removeprefix("font.")
        if name == "bold":
            font.bold = flag(value)
        elif name == "italic":
            font.italic = flag(value)
        elif name == "underline":
            font.underline = flag(value)
        elif name == "size":
            font.size = Pt(points(value))
        elif key in {"font", "font.name"}:
            font.name = str(value)
        elif name == "color":
            font.color.rgb = RGBColor.from_string(hex_color(value))


def set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run._r.getparent().remove(run._r)


def apply_paragraph_props(document: Any, paragraph: Paragraph, props: dict[str, Any]) -> None:
    if "style" in props and str(props["style"]).strip():
        paragraph.style = find_style(document, props["style"])
    if "text" in props:
        set_paragraph_text(paragraph, str(props["text"]))
    alignment = str(props.get("alignment") or props.get("align") or "").strip().lower()
    if alignment:
        if alignment not in ALIGNMENTS:
            raise OfficeEngineError(INVALID_REQUEST, "alignment must be left, center, right or justify")
        paragraph.alignment = ALIGNMENTS[alignment]
    for key, attribute in (("space_before", "space_before"), ("space_after", "space_after")):
        if key in props:
            setattr(paragraph.paragraph_format, attribute, Pt(points(props[key])))
    run_props = {key: value for key, value in props.items() if key not in {"text", "style", "alignment", "align"}}
    if run_props:
        for run in paragraph.runs:
            apply_run_props(run, run_props)


def page_break(paragraph: Paragraph) -> None:
    paragraph.add_run().add_break(WD_BREAK.PAGE)


def chart_into(document: Any, paragraph: Paragraph, props: dict[str, Any]) -> None:
    cx = length_emu(props.get("width") or "15cm")
    cy = length_emu(props.get("height") or "8.5cm")
    add_docx_chart(document, chart_spec(props), paragraph=paragraph, cx=cx, cy=cy)


__all__ = [
    "ALIGNMENTS",
    "apply_paragraph_props",
    "apply_run_props",
    "chart_into",
    "find_style",
    "page_break",
    "set_paragraph_text",
]
