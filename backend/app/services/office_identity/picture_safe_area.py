"""Where a picture may go on a slide whose brand must stay visible."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .layout_backdrop import is_light_color

#: Used only when a template shows no positive left offset anywhere, which
#: means it states no gutter of its own. 0.1 inch keeps the picture off the
#: paper edge without pretending to know the design.
DEFAULT_MARGIN_EMU = 91440

#: A protected placeholder is treated as a full-width band — and therefore cuts
#: the safe area vertically — from this share of the picture slot's width.
#: Chrome always counts, whatever its width: it is edge furniture by nature.
BAND_WIDTH_RATIO = 0.8


def template_margin_emu(layouts: list[dict[str, Any]]) -> int:
    per_layout: Counter[int] = Counter()
    for layout in layouts:
        offsets = [
            slot["x_emu"]
            for slot in _all_slots(layout)
            if isinstance(slot.get("x_emu"), int) and slot["x_emu"] > 0
        ]
        if offsets:
            per_layout[min(offsets)] += 1
    if not per_layout:
        return DEFAULT_MARGIN_EMU
    best = max(per_layout.values())
    return min(value for value, count in per_layout.items() if count == best)


def _all_slots(layout: dict[str, Any]) -> list[dict[str, Any]]:
    chrome = [slot for slot in layout.get("chrome_slots", ()) if isinstance(slot, dict)]
    return list(layout.get("slots", ())) + chrome


def _rect_of(slot: dict[str, Any]) -> tuple[int, int, int, int] | None:
    values = (slot.get("x_emu"), slot.get("y_emu"), slot.get("w_emu"), slot.get("h_emu"))
    if any(not isinstance(value, int) for value in values):
        return None
    x_emu, y_emu, width, height = values  # type: ignore[misc]
    if width <= 0 or height <= 0:
        return None
    return x_emu, y_emu, width, height


def protected_slots(
    layout: dict[str, Any], occupied_idx: set[int]
) -> list[dict[str, Any]]:
    protected: list[dict[str, Any]] = []
    for slot in _all_slots(layout):
        role = str(slot.get("role") or "")
        if role in {"title", "chrome"} or int(slot.get("idx") or 0) in occupied_idx:
            if role != "picture":
                protected.append(slot)
    return protected


def safe_picture_rect(
    layout: dict[str, Any],
    picture_slot: dict[str, Any],
    margin: int,
    occupied_idx: set[int] | None = None,
) -> dict[str, int] | None:
    slot_rect = _rect_of(picture_slot)
    if slot_rect is None:
        return None
    slot_x, slot_y, slot_w, slot_h = slot_rect
    left = slot_x + margin
    top = slot_y + margin
    right = slot_x + slot_w - margin
    bottom = slot_y + slot_h - margin
    if right <= left or bottom <= top:
        return None

    for slot in protected_slots(layout, occupied_idx or set()):
        band = _rect_of(slot)
        if band is None:
            continue
        band_x, band_y, band_w, band_h = band
        is_chrome = str(slot.get("role")) == "chrome"
        if not is_chrome and band_w < slot_w * BAND_WIDTH_RATIO:
            # A narrow protected box does not split the slot into a clean
            # band; cutting on it would remove more area than it protects.
            continue
        if band_y + band_h <= top or band_y >= bottom:
            continue  # already outside the working area
        band_center = band_y + band_h / 2
        if band_center < (top + bottom) / 2:
            top = max(top, band_y + band_h + margin)
        else:
            bottom = min(bottom, band_y - margin)
        if bottom <= top:
            return None

    if right <= left or bottom <= top:
        return None
    return {"x_emu": left, "y_emu": top, "w_emu": right - left, "h_emu": bottom - top}


def gutter_inset(picture_slot: dict[str, Any], margin: int) -> dict[str, int] | None:
    rect = _rect_of(picture_slot)
    if rect is None:
        return None
    x_emu, y_emu, width, height = rect
    if width <= 2 * margin or height <= 2 * margin:
        return None
    return {
        "x_emu": x_emu + margin,
        "y_emu": y_emu + margin,
        "w_emu": width - 2 * margin,
        "h_emu": height - 2 * margin,
    }


# ---------------------------------------------------------------------------
# title legibility
# ---------------------------------------------------------------------------


def _backdrop_slots(layout: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        slot
        for slot in _all_slots(layout)
        if slot.get("has_fill") and str(slot.get("role")) not in {"picture", "media"}
    ]


def has_title_backdrop(layout: dict[str, Any]) -> bool:
    if layout.get("has_background"):
        return True
    titles = [slot for slot in _all_slots(layout) if str(slot.get("role")) == "title"]
    if any(slot.get("has_fill") for slot in titles):
        return True
    title_idx = {int(slot.get("idx") or 0) for slot in titles}
    return any(
        title_idx & {int(index) for index in (slot.get("covers") or ())}
        for slot in _backdrop_slots(layout)
    )


def title_is_legible(layout: dict[str, Any]) -> bool:
    if has_title_backdrop(layout):
        return True
    titles = [slot for slot in _all_slots(layout) if str(slot.get("role")) == "title"]
    return not any(is_light_color(slot.get("font_color")) for slot in titles)


__all__ = [
    "BAND_WIDTH_RATIO",
    "DEFAULT_MARGIN_EMU",
    "gutter_inset",
    "has_title_backdrop",
    "title_is_legible",
    "protected_slots",
    "safe_picture_rect",
    "template_margin_emu",
]
