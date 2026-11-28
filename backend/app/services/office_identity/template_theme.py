"""Theme of a template, resolved through its first slide master."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import COLOR_NAMES, NS_A
from .package import PRESENTATION_PART, PresentationPackage

_THEME_COLOR_SLOTS = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
)


# ---------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------


def _theme_colors(theme_root: ET.Element) -> dict[str, dict[str, str]]:
    scheme = theme_root.find(f".//{{{NS_A}}}clrScheme")
    colors: dict[str, dict[str, str]] = {}
    if scheme is None:
        return colors
    for child in list(scheme):
        slot = child.tag.split("}")[-1]
        nodes = list(child)
        if not nodes:
            continue
        value = str(nodes[0].attrib.get("lastClr") or nodes[0].attrib.get("val") or "").upper()
        if not value:
            continue
        label, description = COLOR_NAMES.get(slot, (slot, ""))
        colors[slot] = {"hex": f"#{value}", "name": label, "description": description}
    return {slot: colors[slot] for slot in _THEME_COLOR_SLOTS if slot in colors}


def _theme_fonts(theme_root: ET.Element) -> dict[str, str]:
    scheme = theme_root.find(f".//{{{NS_A}}}fontScheme")
    fonts: dict[str, str] = {}
    if scheme is None:
        return fonts
    for style in list(scheme):
        style_name = style.tag.split("}")[-1]
        if style_name not in {"majorFont", "minorFont"}:
            continue
        latin = style.find(f"{{{NS_A}}}latin")
        typeface = str(latin.attrib.get("typeface") or "").strip() if latin is not None else ""
        if typeface:
            fonts[style_name] = typeface
    return fonts


def _extract_theme(
    package: PresentationPackage, master_parts: list[str], warnings: list[str]
) -> dict[str, Any]:
    theme_part: str | None = None
    theme_source = "unresolved"
    if master_parts:
        theme_part = package.theme_for_master(master_parts[0])
        if theme_part:
            theme_source = f"{PRESENTATION_PART} -> {master_parts[0]} -> {theme_part}"
    if theme_part is None:
        fallback = "ppt/theme/theme1.xml"
        if fallback in package.names:
            theme_part = fallback
            theme_source = f"fallback:{fallback}"
            warnings.append("theme not resolvable through the slide master; fell back to theme1.xml")
    theme_root = package.xml(theme_part) if theme_part else None
    if theme_root is None:
        warnings.append("no readable theme part in the package")
        return {"theme_name": "", "theme_part": theme_part or "", "theme_source": theme_source,
                "fonts": {}, "colors": {}}
    fonts = _theme_fonts(theme_root)
    return {
        "theme_name": str(theme_root.attrib.get("name") or "").strip(),
        "theme_part": theme_part or "",
        "theme_source": theme_source,
        "fonts": {
            "major": fonts.get("majorFont", ""),
            "minor": fonts.get("minorFont", ""),
        },
        "colors": _theme_colors(theme_root),
    }


__all__ = ["_extract_theme"]
