"""Resolve the default font size of a layout placeholder."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_A, NS_P

#: Which master text style governs a slot's default size. PowerPoint routes
#: title placeholders through ``titleStyle`` and body/subtitle placeholders
#: through ``bodyStyle``; everything else falls to ``otherStyle``.
TEXT_STYLE_FOR_ROLE = {
    "title": "titleStyle",
    "subtitle": "bodyStyle",
    "content": "bodyStyle",
}


def font_size_pt(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = int(raw) / 100.0
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def master_text_sizes(master: ET.Element | None) -> dict[str, float]:
    styles = master.find(f"{{{NS_P}}}txStyles") if master is not None else None
    sizes: dict[str, float] = {}
    for style in list(styles) if styles is not None else []:
        level = style.find(f"{{{NS_A}}}lvl1pPr")
        props = level.find(f"{{{NS_A}}}defRPr") if level is not None else None
        size = font_size_pt(props.attrib.get("sz") if props is not None else None)
        if size is not None:
            sizes[style.tag.split("}")[-1]] = size
    return sizes


def slot_font_color(shape: ET.Element) -> str | None:
    body = shape.find(f".//{{{NS_P}}}txBody")
    style = body.find(f"{{{NS_A}}}lstStyle") if body is not None else None
    level = style.find(f"{{{NS_A}}}lvl1pPr") if style is not None else None
    props = level.find(f"{{{NS_A}}}defRPr") if level is not None else None
    fill = props.find(f"{{{NS_A}}}solidFill") if props is not None else None
    for child in list(fill) if fill is not None else []:
        kind = child.tag.split("}")[-1]
        value = str(child.attrib.get("val") or child.attrib.get("lastClr") or "").strip()
        if not value:
            continue
        if kind == "srgbClr":
            return f"#{value.upper()}"
        if kind == "schemeClr":
            return f"scheme:{value}"
    return None


def slot_font_size(
    shape: ET.Element, role: str, master_sizes: dict[str, float]
) -> float | None:
    body = shape.find(f".//{{{NS_P}}}txBody")
    style = body.find(f"{{{NS_A}}}lstStyle") if body is not None else None
    level = style.find(f"{{{NS_A}}}lvl1pPr") if style is not None else None
    props = level.find(f"{{{NS_A}}}defRPr") if level is not None else None
    override = font_size_pt(props.attrib.get("sz") if props is not None else None)
    if override is not None:
        return override
    return master_sizes.get(TEXT_STYLE_FOR_ROLE.get(role, "otherStyle"))


__all__ = [
    "TEXT_STYLE_FOR_ROLE",
    "font_size_pt",
    "master_text_sizes",
    "slot_font_color",
    "slot_font_size",
]
