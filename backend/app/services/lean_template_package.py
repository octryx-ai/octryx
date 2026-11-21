"""OOXML package helpers of the lean template builder: namespaces, relationships, slide order.

Importing this module registers the presentation namespaces with ElementTree, so
serialized parts keep their usual prefixes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

# Register all namespaces to prevent ns0: prefixes
_NAMESPACES = {
    "": NS_CT,
    "r": NS_R,
    "p": NS_P,
    "a": NS_A,
    "rel": NS_REL,
}
for _prefix, _uri in _NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

# Additional namespaces commonly found in presentations
_EXTRA_NS = {
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p15": "http://schemas.microsoft.com/office/powerpoint/2012/main",
    "p16cid": "http://schemas.microsoft.com/office/powerpoint/2016/slideChunkId",
    "p16sld": "http://schemas.microsoft.com/office/powerpoint/2016/sldId",
    "p16pr": "http://schemas.microsoft.com/office/powerpoint/2016/pptx/re/renderContext",
    "p16chu": "http://schemas.microsoft.com/office/powerpoint/2016/pptx/chunkdatauri",
    "p16csr": "http://schemas.microsoft.com/office/powerpoint/2016/createdSpecialSlideRanges",
}
for _prefix, _uri in _EXTRA_NS.items():
    ET.register_namespace(_prefix, _uri)


def _serialize_xml_with_ns(root: ET.Element, default_ns: str) -> bytes:
    """Serialize XML with correct default namespace (no ns0: prefix)."""
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Fix ns0: prefix issue: replace 'xmlns:ns0="URI"' with 'xmlns="URI"' and 'ns0:' with ''
    prefixed_decl = f'xmlns:ns0="{default_ns}"'.encode()
    default_decl = f'xmlns="{default_ns}"'.encode()
    data = data.replace(prefixed_decl, default_decl)
    data = data.replace(b"ns0:", b"")
    return data


PRESENTATION_CT = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
TEMPLATE_CT = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"

SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
IMAGE_REL_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/video",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio",
    "http://schemas.microsoft.com/office/2007/relationships/media",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
}


def _read_rels(zf: zipfile.ZipFile, rels_path: str) -> list[dict[str, str]]:
    """Parse a .rels file and return list of {Id, Type, Target} dicts."""
    if rels_path not in zf.namelist():
        return []
    root = ET.fromstring(zf.read(rels_path))
    return [
        {
            "Id": el.get("Id", ""),
            "Type": el.get("Type", ""),
            "Target": el.get("Target", ""),
        }
        for el in root.findall(f"{{{NS_REL}}}Relationship")
    ]


def _resolve_target(base_dir: str, target: str) -> str:
    """Resolve a relationship Target relative to base_dir into a zip path."""
    if target.startswith("/"):
        return target.lstrip("/")
    parts = base_dir.rstrip("/").split("/")
    for part in target.split("/"):
        if part == "..":
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _collect_media_refs(zf: zipfile.ZipFile, xml_path: str) -> set[str]:
    """Return set of media zip-paths referenced by xml_path via its .rels file.
    Collects ALL targets under ppt/media/ regardless of relationship type."""
    base_dir = str(Path(xml_path).parent)
    stem = Path(xml_path).name
    rels_path = f"{base_dir}/_rels/{stem}.rels"
    media: set[str] = set()
    for rel in _read_rels(zf, rels_path):
        target = rel.get("Target", "")
        resolved = _resolve_target(base_dir, target)
        # Include any file that ends up in ppt/media/
        if "ppt/media/" in resolved or resolved.startswith("media/"):
            media.add(resolved)
    return media


def _get_slide_order(zf: zipfile.ZipFile) -> list[str]:
    """Return slide zip-paths in presentation order."""
    pres = ET.fromstring(zf.read("ppt/presentation.xml"))
    rels = {
        r["Id"]: r["Target"] for r in _read_rels(zf, "ppt/_rels/presentation.xml.rels") if r["Type"] == SLIDE_REL_TYPE
    }
    slide_id_list = pres.find(f"{{{NS_P}}}sldIdLst")
    result = []
    if slide_id_list is not None:
        for sld_id in slide_id_list:
            r_id = sld_id.get(f"{{{NS_R}}}id")
            if r_id and r_id in rels:
                target = rels[r_id]
                if not target.startswith("/"):
                    target = "ppt/" + target.lstrip("../")
                result.append(target)
    return result


def _build_layout_to_example_slide(zf: zipfile.ZipFile) -> dict[str, int]:
    """
    Returns {slideLayout_stem: best_slide_1_based_index}.
    Picks the slide with the FEWEST shapes for each layout (cleanest example).
    """
    slides_in_order = _get_slide_order(zf)
    layout_to_slides: dict[str, list[tuple[int, int]]] = defaultdict(list)  # layout → [(slide_idx_1based, shape_count)]

    for i, slide_path in enumerate(slides_in_order, start=1):
        rels_path = f"{Path(slide_path).parent}/_rels/{Path(slide_path).name}.rels"
        for rel in _read_rels(zf, rels_path):
            if "slideLayout" in rel.get("Target", ""):
                m = re.search(r"(slideLayout\d+)", rel["Target"])
                if m:
                    # Count shapes
                    try:
                        root = ET.fromstring(zf.read(slide_path))
                        count = len(root.findall(f".//{{{NS_P}}}sp"))
                    except Exception:
                        count = 999
                    layout_to_slides[m.group(1)].append((i, count))

    return {layout: min(slides, key=lambda x: x[1])[0] for layout, slides in layout_to_slides.items() if slides}


def _clear_text_in_xml(data: bytes) -> bytes:
    """Empty all <a:t> text nodes in slide XML while preserving structure."""
    try:
        root = ET.fromstring(data)
        for node in root.findall(f".//{{{NS_A}}}t"):
            node.text = ""
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except ET.ParseError:
        return data
