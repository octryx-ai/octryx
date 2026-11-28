"""Office document parsing helpers for DOCX/XLSX (theme, colors, fonts)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

COLOR_NAMES: dict[str, tuple[str, str]] = {
    "dk1": ("Black / dark text", "Primary text on light backgrounds"),
    "lt1": ("White / light text", "Text on dark backgrounds"),
    "dk2": ("Secondary dark", "Secondary text"),
    "lt2": ("Secondary light", "Dividers and subtle backgrounds"),
    "accent1": ("Accent 1", "Primary brand accent"),
    "accent2": ("Accent 2", "Secondary brand accent"),
    "accent3": ("Accent 3", "Additional accent"),
    "accent4": ("Accent 4", "Additional accent"),
    "accent5": ("Accent 5", "Additional accent"),
    "accent6": ("Accent 6", "Additional accent"),
    "hlink": ("Hyperlink", "Hyperlinks"),
    "folHlink": ("Visited hyperlink", "Visited hyperlinks"),
}


def _hex_color(el: ET.Element) -> str:
    val = str(el.attrib.get("val") or el.attrib.get("lastClr") or "").upper()
    return f"#{val}" if val else ""


def _theme_schemes(root: ET.Element) -> tuple[ET.Element | None, ET.Element | None]:
    ns_map = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    return root.find(".//a:clrScheme", ns_map), root.find(".//a:fontScheme", ns_map)


def _find_theme_schemes(extracted_root: Path) -> tuple[ET.Element | None, ET.Element | None]:
    # Word / Excel: the shared theme is in word/theme/ or xl/theme/
    for theme_dir in (extracted_root / "word", extracted_root / "xl"):
        if not theme_dir.exists():
            continue
        theme_files = list(theme_dir.glob("theme/theme*.xml"))
        if theme_files:
            root = xml_root(theme_files[0])
            if root is not None:
                return _theme_schemes(root)

        # Fallback: check direct theme1.xml
        direct = theme_dir / "theme1.xml"
        if direct.exists():
            root = xml_root(direct)
            if root is not None:
                return _theme_schemes(root)
    return None, None


def _page_dimensions(extracted_root: Path) -> dict[str, Any]:
    slide_dimensions: dict[str, Any] = {}
    doc_settings_paths = [
        extracted_root / "word" / "settings.xml",
        extracted_root / "xl" / "workbook.xml",
    ]
    for sp in doc_settings_paths:
        if not sp.exists():
            continue
        root = xml_root(sp)
        if root is None:
            continue
        # Check for page size in document settings
        for tag in root.iter():
            if tag.tag.endswith("}pgSz"):
                w = tag.attrib.get("w") or tag.attrib.get("cx")
                h = tag.attrib.get("h") or tag.attrib.get("cy")
                if w and h:
                    # Office EMU: 914400 EMU = 1 inch. Convert to cm (1 inch = 2.54 cm)
                    try:
                        slide_dimensions = {
                            "width_cm": round(int(w) / 914400 * 2.54, 2),
                            "height_cm": round(int(h) / 914400 * 2.54, 2),
                        }
                    except (ValueError, TypeError):
                        pass
                break
    return slide_dimensions


def _scheme_colors(color_scheme: ET.Element | None) -> dict[str, Any]:
    colors: dict[str, Any] = {}
    if color_scheme is not None:
        for child in list(color_scheme):
            slot = child.tag.split("}")[-1]
            color_el = list(child)[0] if list(child) else None
            if color_el is None:
                continue
            hex_val = _hex_color(color_el)
            if not hex_val or hex_val == "#":
                continue
            label, description = COLOR_NAMES.get(slot, (slot, ""))
            colors[slot] = {
                "hex": hex_val,
                "name": label,
                "description": description,
            }
    return colors


def _scheme_fonts(font_scheme: ET.Element | None) -> dict[str, str]:
    fonts: dict[str, str] = {}
    if font_scheme is not None:
        for style in list(font_scheme):
            style_name = style.tag.split("}")[-1]
            latin = style.find(f"{{{NS_A}}}latin")
            if latin is not None:
                fonts[style_name] = str(latin.attrib.get("typeface") or "").strip()
    return fonts


def extract_office_document_theme(extracted_root: Path) -> dict[str, Any]:
    color_scheme, font_scheme = _find_theme_schemes(extracted_root)
    slide_dimensions = _page_dimensions(extracted_root)
    colors = _scheme_colors(color_scheme)
    fonts = _scheme_fonts(font_scheme)

    font_family = fonts.get("majorFont", fonts.get("minorFont", "")).strip()
    if not font_family:
        font_family = fonts.get("bodyFont", "")

    return {
        "theme_name": "",
        "font_family": font_family,
        "color_scheme": colors,
        "fonts": fonts,
        "slide_dimensions": slide_dimensions,
    }


def extract_office_document_summary(
    *,
    profile_id: str,
    name: str,
    source_file_name: str,
    brand: dict[str, Any],
    doc_type: str,
    profile_root: Path,
) -> dict[str, Any]:
    color_list = [
        {
            "token": token,
            "hex": info.get("hex"),
            "name": info.get("name"),
        }
        for token, info in list((brand.get("color_scheme") or {}).items())[:8]
    ]

    doc_type_label = {"docx": "Word", "xlsx": "Excel"}.get(doc_type, doc_type.upper())
    return {
        "id": profile_id,
        "name": name,
        "source_file_name": source_file_name,
        "theme_name": brand.get("theme_name") or "",
        "font_family": brand.get("font_family") or "",
        "colors": color_list,
        "office_template_type": doc_type,
        "doc_type_label": doc_type_label,
        "layout_count": 0,
        "corporate_safe_layout_count": 0,
        "recommended_layouts": [],
        "icon_count": 0,
        "icon_categories": [],
        "profile_root": str(profile_root),
    }


def generate_office_document_guide(
    summary: dict[str, Any],
    doc_type: str,
) -> str:
    profile_name = summary.get("name") or "Profile"
    font_family = summary.get("font_family") or "Arial"
    theme_name = summary.get("theme_name") or "-"
    color_lines = [
        f"| `{c.get('token')}` | `{c.get('hex')}` | {c.get('name')} |"
        for c in (summary.get("colors") or [])
    ]

    lines = [
        f"# Corporate Identity Guide: {profile_name}",
        "",
        "## Core Rules",
        "",
        "## Brand",
        f"- Template: {profile_name} | Theme: {theme_name} | Font: {font_family}",
        f"- Document type: {doc_type.upper()}",
        "",
        "## Color Palette",
        "| Token | Hex | Name |",
        "|-------|-----|------|",
    ]
    lines.extend(color_lines or ["| - | - | No palette detected |"])
    lines.append("")
    lines.append("## Usage")
    lines.append(
        f"Use this {doc_type.upper()} template as the default for Office document generation. "
        "Apply brand colors and the configured font family when creating or styling content."
    )
    return "\n".join(lines)


def xml_root(path: Path) -> ET.Element | None:
    if not path.exists():
        return None
    try:
        return ET.fromstring(path.read_bytes())
    except ET.ParseError:
        return None


NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
