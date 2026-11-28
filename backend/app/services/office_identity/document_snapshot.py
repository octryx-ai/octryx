"""Deterministic evidence brief of a Word template — its *style* catalog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.style import WD_STYLE_TYPE

from ..error_facts import error_type
from .document_branding import extract_branding, extract_theme

SNAPSHOT_KIND = "office_document_style_snapshot"
SNAPSHOT_VERSION = 1

#: Semantic role -> the built-in style names that fill it, most specific first.
#: A template that renames these is matched by :func:`_role_of_style` on the
#: normalised name; unmatched styles keep their own slug as the role.
_ROLE_BY_NAME = {
    "title": ("title",),
    "subtitle": ("subtitle",),
    "heading1": ("heading 1", "heading1"),
    "heading2": ("heading 2", "heading2"),
    "heading3": ("heading 3", "heading3"),
    "heading4": ("heading 4", "heading4"),
    "body": ("body text", "body", "normal"),
    "quote": ("intense quote", "quote"),
    "caption": ("caption",),
    "list_bullet": ("list bullet", "list paragraph"),
    "list_number": ("list number",),
}
#: The roles the composer looks for, in the order it prefers to fill a slot.
_HEADING_ROLES = ("heading1", "heading2", "heading3", "heading4")


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _role_of_style(name: str) -> str:
    normalized = _normalize(name)
    for role, candidates in _ROLE_BY_NAME.items():
        if normalized in candidates:
            return role
    return _slug(name)


def _emu(value: Any) -> int | None:
    return int(value) if value is not None else None


def _pt(length: Any) -> float | None:
    try:
        return round(float(length.pt), 2) if length is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _resolved_font(style: Any) -> dict[str, Any]:
    name = size = bold = italic = color = None
    seen: set[int] = set()
    current = style
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        font = getattr(current, "font", None)
        if font is not None:
            if name is None:
                name = font.name
            if size is None:
                size = _pt(font.size)
            if bold is None:
                bold = font.bold
            if italic is None:
                italic = font.italic
            if color is None:
                try:
                    if font.color is not None and font.color.type is not None:
                        color = str(font.color.rgb)
                except (AttributeError, ValueError):
                    color = None
        current = getattr(current, "base_style", None)
    return {"name": name, "size_pt": size, "bold": bold, "italic": italic, "color": color}


def _paragraph_format(style: Any) -> dict[str, Any]:
    fmt = getattr(style, "paragraph_format", None)
    if fmt is None:
        return {}
    alignment = getattr(fmt, "alignment", None)
    return {
        "alignment": str(alignment) if alignment is not None else None,
        "space_before_pt": _pt(getattr(fmt, "space_before", None)),
        "space_after_pt": _pt(getattr(fmt, "space_after", None)),
        "line_spacing": getattr(fmt, "line_spacing", None),
    }


def _page(document: Document) -> dict[str, Any]:
    if not document.sections:
        return {}
    section = document.sections[0]
    raw_orientation = section.orientation
    orientation = getattr(raw_orientation, "name", str(raw_orientation)) if raw_orientation is not None else None
    return {
        "width_emu": _emu(section.page_width),
        "height_emu": _emu(section.page_height),
        "orientation": orientation,
        "margins_emu": {
            "left": _emu(section.left_margin),
            "right": _emu(section.right_margin),
            "top": _emu(section.top_margin),
            "bottom": _emu(section.bottom_margin),
        },
    }


def _collect_styles(document: Document) -> tuple[list[dict[str, Any]], dict[str, str]]:
    styles: list[dict[str, Any]] = []
    role_to_style: dict[str, str] = {}
    for style in document.styles:
        style_type = style.type
        if style_type not in (WD_STYLE_TYPE.PARAGRAPH, WD_STYLE_TYPE.CHARACTER):
            continue
        name = str(style.name or "").strip()
        if not name:
            continue
        role = _role_of_style(name)
        record = {
            "name": name,
            "style_id": str(getattr(style, "style_id", "") or ""),
            "type": "paragraph" if style_type == WD_STYLE_TYPE.PARAGRAPH else "character",
            "role": role,
            "builtin": bool(getattr(style, "builtin", False)),
            "base_style": str(style.base_style.name) if getattr(style, "base_style", None) else None,
            "font": _resolved_font(style),
        }
        if style_type == WD_STYLE_TYPE.PARAGRAPH:
            record["paragraph"] = _paragraph_format(style)
            # First paragraph style to claim a role wins; the template's own
            # order puts its canonical style first.
            if role in _ROLE_BY_NAME and role not in role_to_style:
                role_to_style[role] = name
        styles.append(record)
    return styles, role_to_style


def build_document_snapshot(template_path: str | Path) -> dict[str, Any]:
    """Extract the deterministic style brief of a Word template."""
    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"template not found: {path.name}")
    try:
        document = Document(str(path))
    except Exception as exc:  # python-docx raises a bare Exception on bad packages
        raise ValueError(f"not a readable Word document: {path.name} (error_type={error_type(exc)})") from exc

    warnings: list[str] = []
    styles, role_to_style = _collect_styles(document)

    if "body" not in role_to_style and any(s["name"] == "Normal" for s in styles):
        role_to_style["body"] = "Normal"
    heading_levels = [role for role in _HEADING_ROLES if role in role_to_style]
    if not heading_levels:
        warnings.append("template defines no Heading styles; sections will use the body style")

    theme = extract_theme(path)
    branding = extract_branding(document, path)

    return {
        "kind": SNAPSHOT_KIND,
        "version": SNAPSHOT_VERSION,
        "source_file": path.name,
        "page": _page(document),
        "theme": theme,
        "branding": branding,
        "styles": styles,
        "roles": role_to_style,
        "heading_levels": heading_levels,
        "summary": {
            "style_count": len(styles),
            "paragraph_style_count": sum(1 for s in styles if s["type"] == "paragraph"),
            "roles_available": sorted(role_to_style),
            "has_title": "title" in role_to_style,
            "heading_depth": len(heading_levels),
            "theme_fonts": theme.get("fonts") or {},
            "brand_color_count": len(theme.get("colors") or {}),
            "logo_count": branding.get("logo_count", 0),
            "has_letterhead": bool(branding.get("footer_text") or branding.get("header_has_graphic")),
        },
        "warnings": warnings,
    }


def style_for_role(snapshot: dict[str, Any], role: str, *, default: str = "Normal") -> str:
    roles = snapshot.get("roles") if isinstance(snapshot, dict) else None
    if isinstance(roles, dict) and roles.get(role):
        return str(roles[role])
    return default


__all__ = ["build_document_snapshot", "style_for_role", "SNAPSHOT_KIND", "SNAPSHOT_VERSION"]
