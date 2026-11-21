"""PowerPoint text and shape formatting (python-pptx): text, alignment, fonts, geometry, fill and line."""

from __future__ import annotations

import copy
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

from .paths import INVALID_REQUEST, OfficeEngineError, flag, hex_color, length_emu, points

ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "centre": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT,
         "justify": PP_ALIGN.JUSTIFY}
VALIGN = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "center": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}


def apply_font(runs: list[Any], props: dict[str, Any]) -> None:
    for run in runs:
        font = run.font
        for key, value in props.items():
            name = key.removeprefix("font.")
            if name == "size":
                font.size = Pt(points(value))
            elif name == "bold":
                font.bold = flag(value)
            elif name == "italic":
                font.italic = flag(value)
            elif name == "underline":
                font.underline = flag(value)
            elif name == "color":
                font.color.rgb = RGBColor.from_string(hex_color(value))
            elif key in {"font", "font.name"}:
                font.name = str(value)


def set_paragraph_text(paragraph: Any, text: str) -> None:
    """Replace one paragraph's text in its first run (its formatting stays); breaks and fields go."""
    element = paragraph._p
    for child in list(element):
        if child.tag.rsplit("}", 1)[-1] in {"br", "fld"}:
            element.remove(child)
    runs = paragraph.runs
    if not runs:
        paragraph.add_run().text = text
        return
    runs[0].text = text
    for extra in runs[1:]:
        extra._r.getparent().remove(extra._r)


def set_text(text_frame: Any, text: str) -> None:
    """Replace the text, one paragraph per line; added lines copy the last paragraph, so bullets and
    levels continue the template's own formatting."""
    lines = str(text).split("\n")
    for extra in list(text_frame.paragraphs)[len(lines):]:
        extra._p.getparent().remove(extra._p)
    while len(text_frame.paragraphs) < len(lines):
        last = text_frame.paragraphs[-1]._p
        last.addnext(copy.deepcopy(last))
    for paragraph, line in zip(text_frame.paragraphs, lines, strict=True):
        set_paragraph_text(paragraph, line)


def apply_text_props(text_frame: Any, props: dict[str, Any]) -> None:
    if "text" in props:
        set_text(text_frame, str(props["text"]))
    align = str(props.get("align") or props.get("alignment") or "").lower()
    if align:
        if align not in ALIGN:
            raise OfficeEngineError(INVALID_REQUEST, "align must be left, center, right or justify")
        for paragraph in text_frame.paragraphs:
            paragraph.alignment = ALIGN[align]
    valign = str(props.get("valign") or "").lower()
    if valign:
        text_frame.vertical_anchor = VALIGN.get(valign, MSO_ANCHOR.TOP)
    if "margin" in props:
        margin = length_emu(props["margin"])
        text_frame.margin_left = text_frame.margin_right = text_frame.margin_top = text_frame.margin_bottom = margin
    if "wrap" in props:
        text_frame.word_wrap = flag(props["wrap"])
    apply_font([run for paragraph in text_frame.paragraphs for run in paragraph.runs], props)


def apply_geometry(shape: Any, props: dict[str, Any]) -> None:
    for key, attribute in (("x", "left"), ("y", "top"), ("width", "width"), ("height", "height")):
        if key in props and str(props[key]).strip() != "":
            setattr(shape, attribute, length_emu(props[key]))
    if "rotation" in props:
        shape.rotation = float(props["rotation"])
    if "name" in props:
        shape.name = str(props["name"])


def apply_fill_line(shape: Any, props: dict[str, Any]) -> None:
    if "fill" in props:
        value = str(props["fill"]).strip().lower()
        if value in {"none", "transparent", ""}:
            shape.fill.background()
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(hex_color(value))
    line_value = props.get("line", props.get("lineColor"))
    if line_value is not None:
        if str(line_value).strip().lower() in {"none", ""}:
            shape.line.fill.background()
        else:
            shape.line.color.rgb = RGBColor.from_string(hex_color(line_value))
    if "lineWidth" in props or "line_width" in props:
        shape.line.width = length_emu(props.get("lineWidth", props.get("line_width")), default_unit="pt")


__all__ = [
    "ALIGN",
    "VALIGN",
    "apply_fill_line",
    "apply_font",
    "apply_geometry",
    "apply_text_props",
    "set_paragraph_text",
    "set_text",
]
