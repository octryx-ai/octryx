"""
lean_template_builder.py

Builds a LEAN AI-ready POTX from a large corporate showcase template.

Given a 30MB+ template with 110 content slides:
  1. Identifies the ONE cleanest example slide per layout
  2. Keeps ONLY those slides
  3. Removes ALL orphaned media (images not referenced by master/layouts/example slides)
  4. Clears text content from example slides (positions preserved, text emptied)
  5. Saves a small (~1-3 MB) POTX that the LLM uses as its starting point

Result: every new presentation starts from this lean template, not the 30MB original.
The lean template contains all layout definitions and one blank example per layout,
so `from_path="/slide[N]"` cloning (add_office_element) works on it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .lean_template_package import (
    NS_CT,
    NS_P,
    NS_R,
    NS_REL,
    PRESENTATION_CT,
    SLIDE_REL_TYPE,
    TEMPLATE_CT,
    _build_layout_to_example_slide,
    _clear_text_in_xml,
    _collect_media_refs,
    _get_slide_order,
    _read_rels,
    _serialize_xml_with_ns,
)


def build_lean_ai_template(
    source: Path,
    output_pptx: Path,
    output_potx: Path,
) -> dict[str, Any]:
    """
    Build a lean AI-ready PPTX and POTX from a large corporate template.

    Args:
        source: Path to the source .potx or .pptx (can be 30MB)
        output_pptx: Path where the lean .pptx will be written
        output_potx: Path where the lean .potx will be written

    Returns:
        dict with: slide_count, layout_count, media_count, size_bytes,
                   example_slide_map {layout_name: lean_slide_index}
    """
    output_pptx.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source) as src:
        new_slide_order = _write_lean_pptx(src, output_pptx)

    # --- 8. Build POTX (change content type) ---
    with zipfile.ZipFile(output_pptx) as src2:
        with zipfile.ZipFile(output_potx, "w", compression=zipfile.ZIP_DEFLATED) as dst2:
            for item in src2.infolist():
                data = src2.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(PRESENTATION_CT.encode(), TEMPLATE_CT.encode())
                dst2.writestr(item, data)

    # --- 9. Build final metadata by reading the actual output lean POTX ---
    lean_slide_index, layout_count, media_count = _lean_template_metadata(output_potx)

    size_bytes = output_potx.stat().st_size
    return {
        "pptx_path": str(output_pptx),
        "potx_path": str(output_potx),
        "slide_count": len(new_slide_order),
        "layout_count": layout_count,
        "media_count": media_count,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 2),
        "example_slide_map": lean_slide_index,  # layout_name → 1-based index in lean template
    }


def _write_lean_pptx(src: zipfile.ZipFile, output_pptx: Path) -> list[str]:
    """Write the lean PPTX from the open source package; returns the kept slide paths in order."""
    all_names = set(src.namelist())

    # --- 1. Find example slides per layout ---
    example_map = _build_layout_to_example_slide(src)  # layoutN → 1-based slide index in source
    slides_in_order = _get_slide_order(src)
    selected_1based = sorted(set(example_map.values()))
    selected_paths = {slides_in_order[i - 1] for i in selected_1based if 0 < i <= len(slides_in_order)}

    # --- 2. Collect media referenced by master(s) ---
    needed_media = _needed_media(src, all_names, selected_paths)

    # --- 3. Determine slide relationship IDs to keep ---
    pres_xml = ET.fromstring(src.read("ppt/presentation.xml"))
    pres_rels_raw = _read_rels(src, "ppt/_rels/presentation.xml.rels")
    slide_rels = [r for r in pres_rels_raw if r["Type"] == SLIDE_REL_TYPE]
    kept_rel_ids, new_slide_order = _kept_slides(slide_rels, selected_paths)

    # --- 4. Rewrite presentation.xml: remove non-kept slide IDs ---
    slide_id_list = pres_xml.find(f"{{{NS_P}}}sldIdLst")
    if slide_id_list is not None:
        for sld_id in list(slide_id_list):
            r_id = sld_id.get(f"{{{NS_R}}}id")
            if r_id not in kept_rel_ids:
                slide_id_list.remove(sld_id)

    # --- 5. Rewrite presentation.xml.rels: remove non-kept slide rels ---
    rels_root = ET.fromstring(src.read("ppt/_rels/presentation.xml.rels"))
    for rel in list(rels_root.findall(f"{{{NS_REL}}}Relationship")):
        if rel.get("Type") == SLIDE_REL_TYPE and rel.get("Id") not in kept_rel_ids:
            rels_root.remove(rel)

    # --- 6. Rewrite [Content_Types].xml: remove non-kept slide entries ---
    ct_root = _pruned_content_types(src, new_slide_order)

    # --- 7. Build the lean zip ---
    parts = {"pres_xml": pres_xml, "rels_root": rels_root, "ct_root": ct_root}
    with zipfile.ZipFile(output_pptx, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            name = item.filename
            if not _should_include(name, selected_paths, needed_media):
                continue
            data = _patched_part(name, src.read(name), selected_paths=selected_paths, **parts)
            dst.writestr(item, data)
    return new_slide_order


def _needed_media(src: zipfile.ZipFile, all_names: set[str], selected_paths: set[str]) -> set[str]:
    needed_media: set[str] = set()
    for name in all_names:
        if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", name):
            needed_media |= _collect_media_refs(src, name)
        if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", name):
            needed_media |= _collect_media_refs(src, name)
    for slide_path in selected_paths:
        needed_media |= _collect_media_refs(src, slide_path)

    # Also keep theme media
    for name in all_names:
        if name.startswith("ppt/theme/") and not name.endswith(".xml"):
            needed_media.add(name)
    return needed_media


def _kept_slides(slide_rels: list[dict[str, str]], selected_paths: set[str]) -> tuple[set[str], list[str]]:
    kept_rel_ids: set[str] = set()
    new_slide_order: list[str] = []  # slide paths to keep, in order
    for i, rel in enumerate(slide_rels):
        # Map rel target → zip path
        target = rel["Target"]
        if not target.startswith("/"):
            slide_zip_path = "ppt/" + target.lstrip("../")
        else:
            slide_zip_path = target.lstrip("/")
        if slide_zip_path in selected_paths:
            kept_rel_ids.add(rel["Id"])
            new_slide_order.append(slide_zip_path)
    return kept_rel_ids, new_slide_order


def _pruned_content_types(src: zipfile.ZipFile, new_slide_order: list[str]) -> ET.Element:
    ct_root = ET.fromstring(src.read("[Content_Types].xml"))
    kept_slide_names = {f"/{p}" for p in new_slide_order} | {
        f"/{p.replace('.xml', '.rels')}" for p in new_slide_order
    }
    for child in list(ct_root):
        pn = child.get("PartName", "")
        if pn.startswith("/ppt/slides/") and pn not in kept_slide_names:
            ct_root.remove(child)
        if pn.startswith("/ppt/notesSlides/"):
            ct_root.remove(child)
    return ct_root


def _should_include(name: str, selected_paths: set[str], needed_media: set[str]) -> bool:
    # Skip non-kept slides
    if name.startswith("ppt/slides/") and not name.startswith("ppt/slides/_rels/"):
        slide_path = name
        return slide_path in selected_paths
    if name.startswith("ppt/slides/_rels/"):
        # Keep only rels for selected slides
        base = name.replace("ppt/slides/_rels/", "ppt/slides/").replace(".rels", "")
        return base in selected_paths
    # Skip notes slides
    if name.startswith("ppt/notesSlides/"):
        return False
    # Skip orphaned media
    if name.startswith("ppt/media/"):
        return name in needed_media
    return True


def _patched_part(
    name: str,
    data: bytes,
    *,
    selected_paths: set[str],
    pres_xml: ET.Element,
    rels_root: ET.Element,
    ct_root: ET.Element,
) -> bytes:
    # Patch presentation.xml
    if name == "ppt/presentation.xml":
        data = _serialize_xml_with_ns(pres_xml, NS_P)

    # Patch presentation rels
    elif name == "ppt/_rels/presentation.xml.rels":
        data = _serialize_xml_with_ns(rels_root, NS_REL)

    # Patch content types: ensure PPTX type (not POTX)
    elif name == "[Content_Types].xml":
        ct_data = _serialize_xml_with_ns(ct_root, NS_CT)
        data = ct_data.replace(TEMPLATE_CT.encode(), PRESENTATION_CT.encode())

    # Patch slide .rels files: remove notes slide references
    elif name.startswith("ppt/slides/_rels/") and name.endswith(".rels"):
        try:
            rel_root = ET.fromstring(data)
            for rel_el in list(rel_root.findall(f"{{{NS_REL}}}Relationship")):
                target = rel_el.get("Target", "")
                rel_type = rel_el.get("Type", "")
                if "notesSlide" in target or "notes" in rel_type.lower():
                    rel_root.remove(rel_el)
            data = _serialize_xml_with_ns(rel_root, NS_REL)
        except ET.ParseError:
            pass

    # Clear text in selected slide XML
    elif name.startswith("ppt/slides/") and name.endswith(".xml") and name in selected_paths:
        data = _clear_text_in_xml(data)
    return data


def _lean_template_metadata(output_potx: Path) -> tuple[dict[str, int], int, int]:
    """Layout name → lean slide index, layout count and media count, read from the written file."""
    # Derive layout_name → lean_slide_index directly from the written file (ground truth).
    lean_slide_index: dict[str, int] = {}
    with zipfile.ZipFile(output_potx) as lean_zf:
        lean_names = set(lean_zf.namelist())
        lean_prs = ET.fromstring(lean_zf.read("ppt/presentation.xml"))
        lean_sld_id_list = lean_prs.find(f"{{{NS_P}}}sldIdLst")
        lean_id_to_target = {
            rel.get("Id"): rel.get("Target") for rel in ET.fromstring(lean_zf.read("ppt/_rels/presentation.xml.rels"))
        }
        if lean_sld_id_list is not None:
            for lean_i, sld in enumerate(lean_sld_id_list, 1):
                r_id = sld.get(f"{{{NS_R}}}id")
                layout_name = _slide_layout_name(lean_zf, lean_names, lean_id_to_target.get(r_id))
                if layout_name:
                    lean_slide_index[layout_name] = lean_i

        layout_count = sum(1 for n in lean_names if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n))
        media_count = sum(1 for n in lean_names if n.startswith("ppt/media/"))
    return lean_slide_index, layout_count, media_count


def _slide_layout_name(lean_zf: zipfile.ZipFile, lean_names: set[str], slide_target: str | None) -> str | None:
    """The name of the layout a lean slide uses; only its first layout relationship counts."""
    if not slide_target:
        return None
    slide_file = slide_target.split("/")[-1].replace(".xml", "")
    rels_path = f"ppt/slides/_rels/{slide_file}.xml.rels"
    if rels_path not in lean_names:
        return None
    for rel in ET.fromstring(lean_zf.read(rels_path)):
        if "slideLayout" in rel.get("Type", ""):
            layout_rel = rel.get("Target", "")
            resolved = "ppt/" + "/".join(layout_rel.lstrip("../").split("/"))
            if resolved in lean_names:
                layout_xml = ET.fromstring(lean_zf.read(resolved))
                c_sld = layout_xml.find(f"{{{NS_P}}}cSld")
                if c_sld is not None:
                    layout_name = c_sld.get("name", "").strip()
                    if layout_name:
                        return layout_name
            return None
    return None
