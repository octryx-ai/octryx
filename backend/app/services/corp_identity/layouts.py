"""Layout extraction helpers for corporate identity templates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.services.office_identity.layout_shapes import category_for_shape

from .layout_structure import layout_content_shape
from .parsing import (
    COLOR_NAMES,
    EMU_PER_CM,
    NS_A,
    NS_P,
    XML_NS,
    icon_zones_for_layout,
    infer_placeholder_purpose,
    is_corporate_safe,
    placeholder_meta,
    shape_name,
    shape_rect_cm,
    text_guideline,
    xml_root,
)


def extract_theme(extracted_root: Path) -> dict[str, Any]:
    theme_root = xml_root(extracted_root / "ppt" / "theme" / "theme1.xml")
    if theme_root is None:
        return {}
    color_scheme = theme_root.find(".//a:clrScheme", XML_NS)
    font_scheme = theme_root.find(".//a:fontScheme", XML_NS)
    colors: dict[str, Any] = {}
    if color_scheme is not None:
        for child in list(color_scheme):
            slot = child.tag.split("}")[-1]
            color_node = list(child)[0] if list(child) else None
            if color_node is None:
                continue
            color = str(color_node.attrib.get("lastClr") or color_node.attrib.get("val") or "").upper()
            if not color:
                continue
            label, description = COLOR_NAMES.get(slot, (slot, ""))
            colors[slot] = {
                "hex": f"#{color}",
                "name": label,
                "description": description,
            }
    fonts: dict[str, str] = {}
    if font_scheme is not None:
        for style in list(font_scheme):
            style_name = style.tag.split("}")[-1]
            latin = style.find(f"{{{NS_A}}}latin")
            if latin is not None:
                fonts[style_name] = str(latin.attrib.get("typeface") or "").strip()
    return {
        "theme_name": str(theme_root.attrib.get("name") or "Corporate Theme").strip() or "Corporate Theme",
        "font_family": fonts.get("majorFont") or fonts.get("minorFont") or "Arial",
        "fonts": fonts,
        "color_scheme": colors,
        "font_sizes": {
            "title_pt": 24,
            "body_l1_pt": 16,
            "body_l2_pt": 14,
            "body_l3_pt": 13,
            "body_l4_pt": 12,
        },
    }


def extract_slide_dimensions(extracted_root: Path) -> dict[str, Any]:
    presentation_root = xml_root(extracted_root / "ppt" / "presentation.xml")
    if presentation_root is None:
        return {}
    slide_size = presentation_root.find("p:sldSz", XML_NS)
    if slide_size is None:
        return {}
    width_emu = int(slide_size.attrib.get("cx", 0) or 0)
    height_emu = int(slide_size.attrib.get("cy", 0) or 0)
    return {
        "width_cm": round(width_emu / EMU_PER_CM, 3),
        "height_cm": round(height_emu / EMU_PER_CM, 3),
        "width_emu": width_emu,
        "height_emu": height_emu,
        "format": "16:9",
    }


def build_layout_to_example_slides(extracted_root: Path) -> dict[str, int]:
    """Return {slideLayoutN_stem: best_slide_number}."""
    from collections import defaultdict

    slides_dir = extracted_root / "ppt" / "slides"
    rels_dir = slides_dir / "_rels"
    layout_to_slides: dict[str, list[int]] = defaultdict(list)
    for rels_path in sorted(
        rels_dir.glob("slide*.xml.rels"), key=lambda p: int("".join(ch for ch in p.stem if ch.isdigit()) or "0")
    ):
        stem = rels_path.stem
        match = re.search(r"slide(\d+)", stem)
        if not match:
            continue
        slide_num = int(match.group(1))
        try:
            content = rels_path.read_text(encoding="utf-8")
        except OSError:
            continue
        layout_match = re.search(r"(slideLayout\d+)\.xml", content)
        if layout_match:
            layout_to_slides[layout_match.group(1)].append(slide_num)

    def shape_count(slide_num: int) -> int:
        slide_path = slides_dir / f"slide{slide_num}.xml"
        root = xml_root(slide_path)
        if root is None:
            return 999
        return len(root.findall(f".//{{{NS_P}}}sp"))

    result: dict[str, int] = {}
    for layout_stem, slide_nums in layout_to_slides.items():
        if slide_nums:
            result[layout_stem] = min(sorted(slide_nums), key=shape_count)
    return result


#: Column x-offsets within this many centimetres count as the same column.
_COLUMN_TOLERANCE_CM = 0.06


def column_pair_purposes(placeholders: list[dict[str, Any]]) -> None:
    """Mark heading/body column pairs by geometry, in place.

    A layout whose body placeholders stand in two or more columns of exactly two
    each — a short one above a taller one — is a topic layout: the upper slot of
    column N is "icon heading N", the lower one "icon body N". Placeholder
    numbering plays no part; templates number these slots however they like.
    """
    bodies = [item for item in placeholders if item.get("placeholder_type") in {"body", "obj"}]
    if len(bodies) < 4 or len(bodies) % 2 or any("x_cm" not in item for item in bodies):
        return
    columns: list[list[dict[str, Any]]] = []
    for item in sorted(bodies, key=lambda entry: (entry.get("x_cm", 0), entry.get("y_cm", 0))):
        if columns and abs(item.get("x_cm", 0) - columns[-1][0].get("x_cm", 0)) <= _COLUMN_TOLERANCE_CM:
            columns[-1].append(item)
        else:
            columns.append([item])
    if len(columns) < 2 or any(len(column) != 2 for column in columns):
        return
    for number, column in enumerate(columns, start=1):
        heading, body = sorted(column, key=lambda entry: entry.get("y_cm", 0))
        for item, purpose in ((heading, f"icon heading {number}"), (body, f"icon body {number}")):
            item["purpose"] = purpose
            item["text_guideline"] = text_guideline(str(item.get("placeholder_type") or ""), purpose)


def _layout_shapes(
    shapes: list[ET.Element],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[ET.Element, dict[str, float] | None]]]:
    """Split a layout's shapes into placeholders, static shapes and the raw (shape, rect) pairs."""
    placeholders: list[dict[str, Any]] = []
    non_placeholder_shapes: list[dict[str, Any]] = []
    raw_shapes: list[tuple[ET.Element, dict[str, float] | None]] = []
    for shape in shapes:
        rect = shape_rect_cm(shape)
        raw_shapes.append((shape, rect))
        placeholder = placeholder_meta(shape)
        if placeholder is None:
            if rect is not None:
                non_placeholder_shapes.append({"name": shape_name(shape), **rect})
            continue
        # A placeholder without its own transform inherits the master's
        # geometry; it still counts for what the layout can hold.
        rect = rect or {}
        placeholder_type, placeholder_index = placeholder
        purpose = infer_placeholder_purpose(placeholder_type, placeholder_index, rect, shape_name(shape))
        placeholders.append(
            {
                "placeholder_type": placeholder_type,
                "placeholder_index": placeholder_index,
                "name": shape_name(shape),
                "purpose": purpose,
                "text_guideline": text_guideline(placeholder_type, purpose),
                **rect,
            }
        )
    column_pair_purposes(placeholders)
    return placeholders, non_placeholder_shapes, raw_shapes


def extract_layout_catalog(
    extracted_root: Path, brand: dict[str, Any], slide_dimensions: dict[str, Any]
) -> dict[str, Any]:
    layouts_dir = extracted_root / "ppt" / "slideLayouts"
    layout_paths = sorted(
        layouts_dir.glob("slideLayout*.xml"),
        key=lambda path: int("".join(ch for ch in path.stem if ch.isdigit()) or "0"),
    )
    layout_example_map = build_layout_to_example_slides(extracted_root)
    layouts: list[dict[str, Any]] = []
    by_category: dict[str, list[str]] = {}
    for index, layout_path in enumerate(layout_paths, start=1):
        root = xml_root(layout_path)
        if root is None:
            continue
        common = root.find(f"{{{NS_P}}}cSld")
        layout_name = str(common.attrib.get("name") if common is not None else "").strip() or layout_path.stem
        placeholders, non_placeholder_shapes, raw_shapes = _layout_shapes(root.findall(f".//{{{NS_P}}}sp"))
        icon_zones = icon_zones_for_layout(placeholders, raw_shapes, slide_dimensions)
        content_shape = layout_content_shape(
            layout_name, placeholders, icon_zones,
            layout_type=str(root.attrib.get("type") or ""), slide_dimensions=slide_dimensions,
        )
        category = category_for_shape(content_shape)
        corporate_safe = is_corporate_safe(placeholders, category)
        layouts.append(
            {
                "index": index,
                "name": layout_name,
                "category": category,
                "content_shape": content_shape,
                "corporate_safe": corporate_safe,
                "example_slide_index": layout_example_map.get(layout_path.stem),
                "placeholders": placeholders,
                "static_shapes": non_placeholder_shapes[:24],
                "icon_zones": icon_zones,
            }
        )
        by_category.setdefault(category, []).append(layout_name)
    safe_layouts = [item for item in layouts if item["corporate_safe"]]
    return {
        "slide_dimensions": slide_dimensions,
        "brand": brand,
        "layouts": layouts,
        "summary": {
            "total_layouts": len(layouts),
            "corporate_safe_count": len(safe_layouts),
            "sample_slide_count": len(list((extracted_root / "ppt" / "slides").glob("slide*.xml"))),
            "by_category": by_category,
        },
    }
