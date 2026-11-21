"""Presentation XML manipulation helpers for AI-ready Office templates."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

PRESENTATION_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
TEMPLATE_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PRESENTATION_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _strip_presentation_slides(source: Path, target: Path) -> None:
    presentation_path = "ppt/presentation.xml"
    rels_path = "ppt/_rels/presentation.xml.rels"

    ET.register_namespace("", PRESENTATION_NS)
    ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    ET.register_namespace("", CONTENT_TYPES_NS)

    with zipfile.ZipFile(source) as src:
        presentation_tree = ET.fromstring(src.read(presentation_path))
        rels_tree = ET.fromstring(src.read(rels_path))
        content_types_tree = ET.fromstring(src.read("[Content_Types].xml"))

        slide_id_list = presentation_tree.find(f"{{{PRESENTATION_NS}}}sldIdLst")
        if slide_id_list is not None:
            for slide_id in list(slide_id_list):
                slide_id_list.remove(slide_id)

        for rel in list(rels_tree.findall(f"{{{PRESENTATION_REL_NS}}}Relationship")):
            rel_type = rel.attrib.get("Type", "")
            target_path = rel.attrib.get("Target", "")
            if (
                rel_type.endswith("/slide")
                or "notesSlide" in rel_type
                or target_path.startswith("slides/")
                or target_path.startswith("notesSlides/")
            ):
                rels_tree.remove(rel)

        for child in list(content_types_tree):
            part_name = child.attrib.get("PartName", "")
            if part_name.startswith("/ppt/slides/") or part_name.startswith("/ppt/notesSlides/"):
                content_types_tree.remove(child)

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                name = item.filename
                if name.startswith("ppt/slides/") or name.startswith("ppt/notesSlides/"):
                    continue
                if name.startswith("ppt/slides/_rels/") or name.startswith("ppt/notesSlides/_rels/"):
                    continue
                data = src.read(name)
                if name == presentation_path:
                    data = ET.tostring(presentation_tree, encoding="utf-8", xml_declaration=True)
                elif name == rels_path:
                    data = ET.tostring(rels_tree, encoding="utf-8", xml_declaration=True)
                elif name == "[Content_Types].xml":
                    data = _serialize_xml_with_default_namespace(content_types_tree, CONTENT_TYPES_NS)
                    data = data.replace(
                        TEMPLATE_MAIN_CONTENT_TYPE.encode("utf-8"),
                        PRESENTATION_MAIN_CONTENT_TYPE.encode("utf-8"),
                    )
                dst.writestr(item, data)


def _layout_inventory(source: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    with zipfile.ZipFile(source) as src:
        layout_names = sorted(
            (
                name
                for name in src.namelist()
                if name.startswith("ppt/slideLayouts/slideLayout") and name.endswith(".xml")
            ),
            key=lambda name: int("".join(ch for ch in Path(name).stem if ch.isdigit()) or "0"),
        )
        for name in layout_names:
            root = ET.fromstring(src.read(name))
            common = root.find(f"{{{PRESENTATION_NS}}}cSld")
            layout_name = str(common.attrib.get("name", "") if common is not None else "").strip()
            placeholders: list[dict[str, Any]] = []
            for shape in root.findall(f".//{{{PRESENTATION_NS}}}sp"):
                placeholder = shape.find(
                    f"{{{PRESENTATION_NS}}}nvSpPr/{{{PRESENTATION_NS}}}nvPr/{{{PRESENTATION_NS}}}ph"
                )
                if placeholder is None:
                    continue
                placeholders.append(
                    {"type": placeholder.attrib.get("type", "body"), "index": placeholder.attrib.get("idx", "")}
                )
            inventory.append({"path": name, "layout_name": layout_name, "placeholders": placeholders})
    return inventory


def _convert_pptx_to_potx(source_pptx: Path, target_potx: Path) -> None:
    with zipfile.ZipFile(source_pptx) as src:
        content_types = src.read("[Content_Types].xml").decode("utf-8")
        content_types = content_types.replace(PRESENTATION_MAIN_CONTENT_TYPE, TEMPLATE_MAIN_CONTENT_TYPE)
        with zipfile.ZipFile(target_potx, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = content_types.encode("utf-8")
                dst.writestr(item, data)


def _serialize_xml_with_default_namespace(root: ET.Element, namespace_uri: str) -> bytes:
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    prefixed = f'xmlns:ns0="{namespace_uri}"'.encode()
    defaulted = f'xmlns="{namespace_uri}"'.encode()
    return data.replace(b"ns0:", b"").replace(prefixed, defaulted)


