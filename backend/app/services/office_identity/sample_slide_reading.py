"""Read one sample slide of a presentation package: filled placeholders, pictures, its layout."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_A, NS_P
from .package import PresentationPackage


def _shape_tree(root: ET.Element) -> ET.Element | None:
    return root.find(f".//{{{NS_P}}}spTree")


def _paragraph_texts(shape: ET.Element) -> list[str]:
    body = shape.find(f"{{{NS_P}}}txBody")
    if body is None:
        return []
    paragraphs: list[str] = []
    for paragraph in body.findall(f"{{{NS_A}}}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{{{NS_A}}}t")).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def filled_placeholders(root: ET.Element) -> dict[int, list[str]]:
    tree = _shape_tree(root)
    if tree is None:
        return {}
    filled: dict[int, list[str]] = {}
    for shape in tree.iter():
        if shape.tag.split("}")[-1] not in {"sp", "pic", "graphicFrame"}:
            continue
        placeholder = shape.find(f".//{{{NS_P}}}ph")
        if placeholder is None:
            continue
        try:
            index = int(placeholder.attrib.get("idx", 0))
        except (TypeError, ValueError):
            index = 0
        paragraphs = _paragraph_texts(shape)
        # A layout can declare the same idx twice only in malformed packages;
        # the first occurrence in document order wins, deterministically.
        filled.setdefault(index, paragraphs)
    return filled


def picture_count(root: ET.Element) -> int:
    tree = _shape_tree(root)
    if tree is None:
        return 0
    return sum(1 for _ in tree.iter(f"{{{NS_P}}}pic"))


def layout_part_of_slide(package: PresentationPackage, slide_part: str) -> str | None:
    for target in package.rels(slide_part).values():
        if target.startswith("ppt/slideLayouts/"):
            return target
    return None


def layout_name(package: PresentationPackage, layout_part: str) -> str:
    root = package.xml(layout_part)
    if root is None:
        return ""
    common = root.find(f"{{{NS_P}}}cSld")
    return str(common.attrib.get("name") if common is not None else "").strip()


def normalized_layout_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


__all__ = [
    "filled_placeholders",
    "layout_name",
    "layout_part_of_slide",
    "normalized_layout_name",
    "picture_count",
]
