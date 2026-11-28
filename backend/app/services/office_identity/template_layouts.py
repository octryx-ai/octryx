"""Layout catalog of a template: slots, geometry, shape and capacity per layout."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_A, NS_P, slugify
from .icon_slots import icon_anchors as _icon_anchors
from .layout_authoring import layout_origin
from .layout_backdrop import has_fill as _has_fill
from .layout_backdrop import paints_backdrop as _paints_backdrop
from .layout_shapes import category_for_shape, classify_layout, slot_role
from .package import PresentationPackage
from .slot_coverage import annotate_coverage
from .slot_text_metrics import master_text_sizes, slot_font_color, slot_font_size

MAX_LAYOUTS = 400
MAX_SLOTS_PER_LAYOUT = 60


def _geometry(shape: ET.Element) -> dict[str, int] | None:
    for props_tag in (f"{{{NS_P}}}spPr", f"{{{NS_A}}}spPr"):
        props = shape.find(props_tag)
        if props is None:
            continue
        transform = props.find(f"{{{NS_A}}}xfrm")
        if transform is None:
            continue
        off = transform.find(f"{{{NS_A}}}off")
        ext = transform.find(f"{{{NS_A}}}ext")
        if off is None and ext is None:
            continue
        try:
            return {
                "x_emu": int(off.attrib.get("x", 0)) if off is not None else 0,
                "y_emu": int(off.attrib.get("y", 0)) if off is not None else 0,
                "w_emu": int(ext.attrib.get("cx", 0)) if ext is not None else 0,
                "h_emu": int(ext.attrib.get("cy", 0)) if ext is not None else 0,
            }
        except (TypeError, ValueError):
            return None
    return None


def _aspect_ratio(rect: dict[str, int] | None) -> float | None:
    if not rect:
        return None
    width = rect.get("w_emu")
    height = rect.get("h_emu")
    if not isinstance(width, int) or not isinstance(height, int) or height <= 0 or width <= 0:
        return None
    return round(width / height, 4)


def _placeholder_shapes(root: ET.Element) -> list[tuple[ET.Element, str, int]]:
    tree = root.find(f".//{{{NS_P}}}spTree")
    if tree is None:
        return []
    found: list[tuple[ET.Element, str, int]] = []
    for shape in tree.iter():
        tag = shape.tag.split("}")[-1]
        if tag not in {"sp", "pic", "graphicFrame"}:
            continue
        placeholder = shape.find(f".//{{{NS_P}}}ph")
        if placeholder is None:
            continue
        placeholder_type = str(placeholder.attrib.get("type") or "obj").strip() or "obj"
        try:
            index = int(placeholder.attrib.get("idx", 0))
        except (TypeError, ValueError):
            index = 0
        found.append((shape, placeholder_type, index))
    return found


def _master_geometry(package: PresentationPackage, master_part: str) -> dict[int, dict[str, int]]:
    master = package.xml(master_part)
    if master is None:
        return {}
    geometry: dict[int, dict[str, int]] = {}
    for shape, _placeholder_type, index in _placeholder_shapes(master):
        rect = _geometry(shape)
        if rect is not None:
            geometry.setdefault(index, rect)
    return geometry


def _layout_slots(
    root: ET.Element,
    inherited: dict[int, dict[str, int]],
    master_sizes: dict[str, float],
    slide_size: dict[str, int],
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for shape, placeholder_type, index in _placeholder_shapes(root):
        rect = _geometry(shape)
        geometry_source = "layout"
        if rect is None:
            rect = inherited.get(index)
            geometry_source = "master" if rect is not None else "none"
        role = slot_role(placeholder_type)
        slots.append(
            {
                "idx": index,
                "placeholder_type": placeholder_type,
                "role": role,
                "geometry_source": geometry_source,
                "aspect_ratio": _aspect_ratio(rect),
                "font_size_pt": slot_font_size(shape, role, master_sizes),
                "font_color": slot_font_color(shape),
                "has_fill": _has_fill(shape),
                **(rect or {"x_emu": None, "y_emu": None, "w_emu": None, "h_emu": None}),
            }
        )
    slots.sort(key=lambda slot: (slot["role"] != "title", slot["idx"], slot["placeholder_type"]))
    slots = slots[:MAX_SLOTS_PER_LAYOUT]
    # Coverage is computed over the *complete* retained slot set, chrome
    # included: a picture that swallows the footer and the slide number is the
    # branding failure the gate has to see.
    annotate_coverage(slots, slide_size)
    return slots


def _layout_key(name: str, part: str, master_index: int, used: set[str]) -> str:
    base = slugify(name, fallback=Path(part).stem.lower())
    key = base
    if key in used:
        key = f"{base}--m{master_index}"
    suffix = 2
    while key in used:
        key = f"{base}--m{master_index}-{suffix}"
        suffix += 1
    used.add(key)
    return key


def _layout_record(
    root: ET.Element, slots: list[dict[str, Any]], name: str, slide_size: dict[str, int]
) -> dict[str, Any]:
    layout_type = str(root.attrib.get("type") or "").strip()
    anchors = _icon_anchors(root, slide_size, _geometry)
    content_shape, capacity = classify_layout(
        name, slots, slide_size, layout_type=layout_type, icon_holders=len(anchors)
    )
    return {
        "category": category_for_shape(content_shape),
        # ``template`` for what the template author wrote,
        # ``derived`` for a layout upload normalisation generated.
        **layout_origin(root),
        # A layout-level background — ``p:bg`` or a slide-filling
        # decorative shape — paints the whole slide, so text on it
        # stays legible without a picture behind it.
        "has_background": _paints_backdrop(root, slide_size, _geometry),
        "content_shape": content_shape,
        "capacity": capacity,
        # Static (non-placeholder) icon holders the composer fills
        # from the template's icon catalog — empty for layouts that
        # ship none. See ``icon_slots``/``icon_embedding``.
        "icon_anchors": anchors,
        "slots": [slot for slot in slots if slot["role"] != "chrome"],
        # Chrome (footer, slide number, date) keeps its full slot
        # record: the gate names what a picture hides, and the safe
        # area derives the bottom brand row from this geometry.
        "chrome_slots": [slot for slot in slots if slot["role"] == "chrome"],
    }


def _extract_layouts(
    package: PresentationPackage,
    master_parts: list[str],
    slide_size: dict[str, int],
    warnings: list[str],
) -> list[dict[str, Any]]:
    layouts: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    seen_parts: set[str] = set()
    for master_index, master_part in enumerate(master_parts, start=1):
        inherited = _master_geometry(package, master_part)
        master_sizes = master_text_sizes(package.xml(master_part))
        for layout_part in package.layout_parts_for_master(master_part):
            if layout_part in seen_parts:
                continue
            seen_parts.add(layout_part)
            root = package.xml(layout_part)
            if root is None:
                warnings.append(f"unreadable layout part {layout_part}")
                continue
            common = root.find(f"{{{NS_P}}}cSld")
            name = str(common.attrib.get("name") if common is not None else "").strip()
            if not name:
                name = Path(layout_part).stem
            slots = _layout_slots(root, inherited, master_sizes, slide_size)
            layouts.append(
                {
                    "key": _layout_key(name, layout_part, master_index, used_keys),
                    "order": len(layouts),
                    "name": name,
                    "part": layout_part,
                    "master_index": master_index,
                    "master_part": master_part,
                    **_layout_record(root, slots, name, slide_size),
                }
            )
    orphans = [part for part in package.all_layout_parts() if part not in seen_parts]
    if orphans:
        warnings.append(f"{len(orphans)} layout parts not referenced by any master were skipped")
    if len(layouts) > MAX_LAYOUTS:
        warnings.append(f"layout catalog truncated to {MAX_LAYOUTS} of {len(layouts)} layouts")
    return layouts[:MAX_LAYOUTS]


__all__ = ["MAX_LAYOUTS", "_extract_layouts", "_geometry"]
