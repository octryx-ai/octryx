"""XML and PPT structure parsing helpers for Office template extraction."""

from __future__ import annotations

import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from app.services.office_template_package.constants import XML_NS


def _read_xml(zip_file: zipfile.ZipFile, name: str) -> ET.Element | None:
    if name not in zip_file.namelist():
        return None
    return ET.fromstring(zip_file.read(name))


def _numeric_office_xml_sort_key(name: str) -> tuple[str, int]:
    match = re.search(r"(\d+)(?=\.xml$)", name)
    return (name, -1) if match is None else (name[: match.start(1)], int(match.group(1)))


def _theme_colors(zip_file: zipfile.ZipFile) -> dict[str, str]:
    root = _read_xml(zip_file, "ppt/theme/theme1.xml")
    if root is None:
        return {}
    scheme = root.find(".//a:clrScheme", XML_NS)
    if scheme is None:
        return {}

    colors: dict[str, str] = {}
    for child in list(scheme):
        tag = child.tag.split("}")[-1]
        if not list(child):
            continue
        color_node = list(child)[0]
        color = color_node.attrib.get("lastClr") or color_node.attrib.get("val") or ""
        if color:
            colors[tag] = color
    return colors


def _slide_size(zip_file: zipfile.ZipFile) -> dict[str, int | str]:
    root = _read_xml(zip_file, "ppt/presentation.xml")
    if root is None:
        return {}
    slide_size = root.find("p:sldSz", XML_NS)
    if slide_size is None:
        return {}

    payload: dict[str, int | str] = {}
    for key in ("cx", "cy", "type"):
        value = slide_size.attrib.get(key)
        if not value:
            continue
        payload[key] = int(value) if value.isdigit() else value
    return payload


def _extract_text_values(root: ET.Element) -> list[str]:
    values: list[str] = []
    for node in root.findall(".//a:t", XML_NS):
        text = (node.text or "").strip()
        if text:
            values.append(text)
    return values


def _slide_summaries(zip_file: zipfile.ZipFile) -> list[dict[str, Any]]:
    slides = sorted(
        [name for name in zip_file.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
        key=_numeric_office_xml_sort_key,
    )
    summaries: list[dict[str, Any]] = []
    for name in slides:
        root = _read_xml(zip_file, name)
        if root is None:
            continue
        values = _extract_text_values(root)
        summaries.append(
            {
                "slide_xml": name,
                "text_sample": values[:12],
                "title": values[0] if values else "",
                "text_count": len(values),
            }
        )
    return summaries


def _layout_summaries(zip_file: zipfile.ZipFile) -> list[dict[str, Any]]:
    layouts = sorted(
        [
            name
            for name in zip_file.namelist()
            if name.startswith("ppt/slideLayouts/slideLayout") and name.endswith(".xml")
        ],
        key=_numeric_office_xml_sort_key,
    )
    payloads: list[dict[str, Any]] = []
    for name in layouts:
        root = _read_xml(zip_file, name)
        if root is None:
            continue
        placeholders: list[dict[str, str]] = []
        for shape in root.findall(".//p:sp", XML_NS):
            placeholder = shape.find(".//p:ph", XML_NS)
            if placeholder is None:
                continue
            placeholders.append({key: value for key, value in placeholder.attrib.items()})
        payloads.append(
            {
                "layout_xml": name,
                "placeholder_count": len(placeholders),
                "placeholders": placeholders,
            }
        )
    return payloads
