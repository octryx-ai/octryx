"""Shared parsing helpers for corporate identity extraction."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

EMU_PER_CM = 360_000
EMU_PER_INCH = 914400
XML_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
NS_P = XML_NS["p"]
NS_A = XML_NS["a"]
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_SVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}

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


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def slugify(value: str, *, fallback: str = "profile") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def icon_slugify(value: str) -> str:
    cleaned = re.sub(r"^ICO_", "", str(value or "").strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower() or "icon"


def safe_upload_name(name: str) -> str:
    cleaned = Path(name or "template.potx").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-.")
    return cleaned or "template.potx"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def profile_root(root: Path, profile_id: str) -> Path:
    return (root / profile_id).resolve()


def xml_root(path: Path) -> ET.Element | None:
    if not path.exists():
        return None
    try:
        return ET.fromstring(path.read_bytes())
    except ET.ParseError:
        return None


def emu_to_cm(raw: Any) -> float:
    try:
        return round(int(raw) / EMU_PER_CM, 3)
    except (TypeError, ValueError):
        return 0.0


def load_rels(path: Path) -> dict[str, str]:
    rels: dict[str, str] = {}
    if not path.exists():
        return rels
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return rels
    for rel in root:
        rel_id = str(rel.attrib.get("Id") or "").strip()
        target = str(rel.attrib.get("Target") or "").strip()
        target = re.sub(r"^\.\./media/", "", target)
        target = re.sub(r"^media/", "", target)
        if rel_id:
            rels[rel_id] = target
    return rels


def ppt_text(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.findall(f".//{{{NS_A}}}t"):
        if node.text:
            parts.append(node.text)
    return " ".join(parts).strip()


def shape_position(element: ET.Element) -> tuple[int, int]:
    shape_props = element.find(f"{{{NS_P}}}spPr")
    if shape_props is None:
        return (0, 0)
    transform = shape_props.find(f"{{{NS_A}}}xfrm")
    if transform is None:
        return (0, 0)
    off = transform.find(f"{{{NS_A}}}off")
    if off is None:
        return (0, 0)
    try:
        return int(off.attrib.get("x", 0)), int(off.attrib.get("y", 0))
    except (TypeError, ValueError):
        return (0, 0)


def shape_rect_cm(element: ET.Element) -> dict[str, float] | None:
    shape_props = element.find(f"{{{NS_P}}}spPr")
    if shape_props is None:
        shape_props = element.find(f"{{{NS_A}}}spPr")
    if shape_props is None:
        return None
    transform = shape_props.find(f"{{{NS_A}}}xfrm")
    if transform is None:
        return None
    off = transform.find(f"{{{NS_A}}}off")
    ext = transform.find(f"{{{NS_A}}}ext")
    if off is None and ext is None:
        return None
    return {
        "x_cm": emu_to_cm(off.attrib.get("x", 0) if off is not None else 0),
        "y_cm": emu_to_cm(off.attrib.get("y", 0) if off is not None else 0),
        "w_cm": emu_to_cm(ext.attrib.get("cx", 0) if ext is not None else 0),
        "h_cm": emu_to_cm(ext.attrib.get("cy", 0) if ext is not None else 0),
    }


def shape_name(element: ET.Element) -> str:
    non_visual = element.find(f".//{{{NS_P}}}cNvPr")
    if non_visual is None:
        non_visual = element.find(f".//{{{NS_A}}}cNvPr")
    return str(non_visual.attrib.get("name") if non_visual is not None else "").strip()


def placeholder_meta(shape: ET.Element) -> tuple[str, int] | None:
    placeholder = shape.find(f".//{{{NS_P}}}ph")
    if placeholder is None:
        return None
    placeholder_type = str(placeholder.attrib.get("type") or "body").strip() or "body"
    try:
        placeholder_index = int(placeholder.attrib.get("idx", 0))
    except (TypeError, ValueError):
        placeholder_index = 0
    return placeholder_type, placeholder_index


def infer_placeholder_purpose(placeholder_type: str, placeholder_index: int, rect: dict[str, float], name: str) -> str:
    lowered = name.lower()
    if placeholder_type in {"title", "ctrTitle"}:
        return "slide title"
    if placeholder_type == "subTitle":
        return "subtitle"
    if placeholder_type == "pic":
        area = rect.get("w_cm", 0) * rect.get("h_cm", 0)
        return "full-slide picture area" if area > 150 else "picture area"
    if placeholder_type == "media":
        return "media area"
    if placeholder_type == "ftr":
        return "footer text"
    if placeholder_type == "dt":
        return "date or time"
    if "agenda" in lowered:
        return "agenda body"
    return "main content area" if rect.get("h_cm", 0) >= 5 else "content area"


def text_guideline(placeholder_type: str, purpose: str) -> dict[str, Any]:
    if placeholder_type in {"title", "ctrTitle"}:
        return {"max_chars": 60, "hint": "One short title line."}
    if placeholder_type == "subTitle":
        return {"max_chars": 120, "hint": "One to two concise lines."}
    if placeholder_type == "body":
        if "icon heading" in purpose:
            return {"max_chars": 40, "hint": "Short heading, two to four words."}
        if "icon body" in purpose:
            return {"max_chars": 200, "hint": "Three to five concise bullet points."}
        return {"max_chars": 600, "hint": "Concise bullets or short paragraphs."}
    return {"max_chars": 160, "hint": ""}


def is_corporate_safe(placeholders: list[dict[str, Any]], category: str) -> bool:
    """Whether a generic deck may use the layout: not a people/contact layout.

    ``category`` comes from the structural classification (where the layout
    name is only a hint).
    """
    if category == "contact":
        return False
    for placeholder in placeholders:
        if placeholder.get("placeholder_type") == "pic":
            purpose = str(placeholder.get("purpose") or "").lower()
            if "portrait" in purpose or "headshot" in purpose:
                return False
    return True


#: Static shapes that count as an icon frame: small, roughly square circles or
#: rounded squares (the same rule as ``office_identity.icon_slots``).
_FRAME_PRESETS = frozenset({"ellipse", "roundRect"})
_FRAME_MAX_AREA_RATIO = 0.08
_FRAME_MAX_ASPECT = 1.35


def _is_icon_frame(rect: dict[str, float], slide_area: float) -> bool:
    width, height = rect.get("w_cm", 0), rect.get("h_cm", 0)
    if width <= 0 or height <= 0 or max(width, height) / min(width, height) > _FRAME_MAX_ASPECT:
        return False
    return slide_area <= 0 or width * height / slide_area <= _FRAME_MAX_AREA_RATIO


def icon_zones_for_layout(
    placeholders: list[dict[str, Any]],
    all_shapes: list[tuple[ET.Element, dict[str, float] | None]],
    slide_dimensions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Icon frames drawn on the layout, else the free area a model may place icons in.

    Decided by structure only: small square circles are frames; a title without body leaves the area under
    it free; a layout without placeholders leaves the whole slide free.
    """
    dims = slide_dimensions or {}
    slide_w = float(dims.get("width_cm") or 25.4)
    slide_h = float(dims.get("height_cm") or 14.288)
    margin = 1.2
    zones: list[dict[str, Any]] = []
    for shape, rect in all_shapes:
        if rect is None or placeholder_meta(shape) is not None:
            continue
        geometry = shape.find(f".//{{{NS_A}}}prstGeom")
        if geometry is not None and geometry.attrib.get("prst") in _FRAME_PRESETS and _is_icon_frame(
            rect, slide_w * slide_h
        ):
            zones.append({**rect, "note": "icon frame"})
    if zones:
        return zones
    kinds = {item.get("placeholder_type") for item in placeholders}
    if kinds & {"title", "ctrTitle"} and not kinds & {"body", "obj"}:
        title = next((item for item in placeholders if item.get("placeholder_type") in {"title", "ctrTitle"}), None)
        title_bottom = (title or {}).get("y_cm", 2.0) + (title or {}).get("h_cm", 1.2) + 0.4
        height = max(slide_h - title_bottom - margin, 1.0)
        return [{"x_cm": margin, "y_cm": title_bottom, "w_cm": slide_w - 2 * margin, "h_cm": height,
                 "note": "free content area"}]
    if not kinds - {"ftr", "sldNum", "dt", "hdr"}:
        return [{"x_cm": margin, "y_cm": margin, "w_cm": slide_w - 2 * margin, "h_cm": slide_h - 2 * margin,
                 "note": "full slide free area"}]
    return []
