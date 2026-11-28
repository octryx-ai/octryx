"""The visible identity of a Word template: theme fonts, colour palette, logo and letterhead."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from docx import Document

_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
#: Theme colour slots, in the order the palette is read; the accents are the
#: brand colours a brand check compares generated text against.
_THEME_COLOR_SLOTS = (
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)


def _color_value(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    srgb = element.find(f"{{{_NS_A}}}srgbClr")
    if srgb is not None and srgb.get("val"):
        return f"#{srgb.get('val').upper()}"
    sys_clr = element.find(f"{{{_NS_A}}}sysClr")
    if sys_clr is not None and sys_clr.get("lastClr"):
        return f"#{sys_clr.get('lastClr').upper()}"
    return None


def extract_theme(path: Path) -> dict[str, Any]:
    theme: dict[str, Any] = {"fonts": {}, "colors": {}}
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [n for n in archive.namelist() if re.match(r"word/theme/theme\d+\.xml$", n)]
            if not candidates:
                return theme
            root = ET.fromstring(archive.read(sorted(candidates)[0]))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return theme

    for role in ("majorFont", "minorFont"):
        node = root.find(f".//{{{_NS_A}}}{role}/{{{_NS_A}}}latin")
        if node is not None and node.get("typeface"):
            theme["fonts"][role] = node.get("typeface")
    scheme = root.find(f".//{{{_NS_A}}}clrScheme")
    if scheme is not None:
        for slot in _THEME_COLOR_SLOTS:
            value = _color_value(scheme.find(f"{{{_NS_A}}}{slot}"))
            if value:
                theme["colors"][slot] = value
    return theme


def extract_branding(document: Document, path: Path) -> dict[str, Any]:
    logos: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            logos = sorted(Path(n).name for n in archive.namelist() if n.startswith("word/media/"))
    except (OSError, zipfile.BadZipFile):
        logos = []

    header_text = footer_text = ""
    header_has_graphic = False
    if document.sections:
        section = document.sections[0]
        header_text = " | ".join(p.text.strip() for p in section.header.paragraphs if p.text.strip())[:400]
        footer_text = " | ".join(p.text.strip() for p in section.footer.paragraphs if p.text.strip())[:400]
        header_xml = section.header.part.blob if section.header is not None else b""
        header_has_graphic = b"<w:drawing" in header_xml or b"<pic:pic" in header_xml
    return {
        "logo_media": logos,
        "logo_count": len(logos),
        "header_text": header_text,
        "footer_text": footer_text,
        "header_has_graphic": header_has_graphic,
    }


__all__ = ["extract_branding", "extract_theme"]
