"""Geometric relations between a layout's slots: coverage and full bleed."""

from __future__ import annotations

from typing import Any

#: A picture slot occupying at least this fraction of the slide is full bleed:
#: it leaves no margin for the branded background, the logo or the footer.
FULL_BLEED_AREA_RATIO = 0.90

#: A slot counts as covered when at least this fraction of *its own* area lies
#: inside another slot's rectangle.
COVER_RATIO = 0.90

#: Roles whose loss makes a slide unbranded when a picture covers them.
BRAND_ROLES = frozenset({"title", "chrome"})


def _rect(slot: dict[str, Any]) -> tuple[int, int, int, int] | None:
    values = (slot.get("x_emu"), slot.get("y_emu"), slot.get("w_emu"), slot.get("h_emu"))
    if any(not isinstance(value, int) for value in values):
        return None
    x_emu, y_emu, width, height = values  # type: ignore[misc]
    if width <= 0 or height <= 0:
        return None
    return x_emu, y_emu, width, height


def covered_fraction(outer: dict[str, Any], inner: dict[str, Any]) -> float:
    first = _rect(outer)
    second = _rect(inner)
    if first is None or second is None:
        return 0.0
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return round((overlap_w * overlap_h) / (bw * bh), 4)


def annotate_coverage(slots: list[dict[str, Any]], slide_size: dict[str, int]) -> None:
    slide_area = int(slide_size.get("width_emu") or 0) * int(slide_size.get("height_emu") or 0)
    for slot in slots:
        rect = _rect(slot)
        ratio = round((rect[2] * rect[3]) / slide_area, 4) if rect and slide_area > 0 else None
        covered = [
            other
            for other in slots
            if other is not slot and covered_fraction(slot, other) >= COVER_RATIO
        ]
        slot["slide_area_ratio"] = ratio
        slot["covers"] = sorted({int(other.get("idx") or 0) for other in covered})
        slot["full_bleed"] = bool(
            slot.get("role") in {"picture", "media"}
            and (
                (ratio is not None and ratio >= FULL_BLEED_AREA_RATIO)
                or any(other.get("role") in BRAND_ROLES for other in covered)
            )
        )


__all__ = ["BRAND_ROLES", "COVER_RATIO", "FULL_BLEED_AREA_RATIO", "annotate_coverage", "covered_fraction"]
