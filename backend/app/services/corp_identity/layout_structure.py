"""What a layout of the corporate identity catalog is, decided by its structure."""

from __future__ import annotations

from typing import Any

from ..office_identity.layout_shapes import classify_layout, slot_role
from .parsing import EMU_PER_CM


def _slot(placeholder: dict[str, Any]) -> dict[str, Any]:
    kind = str(placeholder.get("placeholder_type") or "body")
    slot: dict[str, Any] = {
        "idx": int(placeholder.get("placeholder_index") or 0),
        "placeholder_type": kind,
        "role": slot_role(kind),
    }
    for axis in ("x", "y", "w", "h"):
        value = placeholder.get(f"{axis}_cm")
        slot[f"{axis}_emu"] = int(round(value * EMU_PER_CM)) if isinstance(value, (int, float)) else None
    return slot


def layout_content_shape(
    name: str,
    placeholders: list[dict[str, Any]],
    icon_zones: list[dict[str, Any]],
    *,
    layout_type: str = "",
    slide_dimensions: dict[str, Any] | None = None,
) -> str:
    dims = slide_dimensions or {}
    size = {"width_emu": int(dims.get("width_emu") or 0), "height_emu": int(dims.get("height_emu") or 0)}
    holders = sum(1 for zone in icon_zones if zone.get("note") == "icon frame")
    shape, _capacity = classify_layout(
        name, [_slot(item) for item in placeholders], size, layout_type=layout_type, icon_holders=holders
    )
    return shape


def _body_count(layout: dict[str, Any]) -> int:
    return sum(
        1 for item in layout.get("placeholders") or ()
        if slot_role(str(item.get("placeholder_type") or "body")) == "content"
    )


def layout_hint(layout: dict[str, Any]) -> str:
    shape = str(layout.get("content_shape") or "")
    count = shape.rsplit("_", 1)[-1] if shape[-1:].isdigit() else ""
    fixed = {
        "title_slide": "opening cover slide",
        "section": "chapter / section divider",
        "statement": "large statement / key message",
        "quote": "pull quote with attribution",
        "agenda": "agenda / table of contents",
        "title_only": "title bar only — free canvas below",
        "title_and_subtitle": "title with a supporting subtitle line",
        "bullets": "title + body text / bullets",
        "two_content": "side-by-side comparison of two topics",
        "content_with_picture": "image + text split",
        "picture": "picture with title",
        "picture_full": "full-slide picture",
        "diagram_full": "full-slide diagram",
        "blank": "fully empty canvas for custom content",
    }
    if shape in fixed:
        return fixed[shape]
    if shape.startswith("icons_"):
        return f"{count} visual topics with icon + heading + body"
    if shape.startswith("columns_"):
        return f"{count} columns with heading + body"
    if shape.startswith("image_grid_"):
        return f"grid of {count} pictures"
    if shape.startswith("contact_"):
        return "presenter / team contact details"
    if shape.startswith("content_"):
        return f"{_body_count(layout)} content areas"
    return str(layout.get("category") or "content")


__all__ = ["layout_content_shape", "layout_hint"]
