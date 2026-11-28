"""Fill one slide of a composed deck from its template layout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .composer_plan import ComposerError
from .picture_safe_area import gutter_inset, safe_picture_rect


def drop_sample_slides(presentation: Any) -> int:
    slide_id_list = presentation.slides._sldIdLst
    removed = 0
    for slide_id in list(slide_id_list):
        presentation.part.drop_rel(slide_id.rId)
        slide_id_list.remove(slide_id)
        removed += 1
    return removed


def layout_index(presentation: Any) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for master in presentation.slide_masters:
        for layout in master.slide_layouts:
            index[str(layout.part.partname).lstrip("/")] = layout
    return index


def _ordered_slots(layout: dict[str, Any], role: str) -> list[dict[str, Any]]:
    slots = [slot for slot in layout.get("slots", []) if slot.get("role") == role]
    slots.sort(
        key=lambda slot: (
            slot.get("x_emu") if isinstance(slot.get("x_emu"), int) else 10**9,
            slot.get("y_emu") if isinstance(slot.get("y_emu"), int) else 10**9,
            slot.get("idx"),
        )
    )
    return slots


def _content_columns(layout: dict[str, Any]) -> list[list[dict[str, Any]]]:
    slots = _ordered_slots(layout, "content")
    paired = int((layout.get("capacity") or {}).get("paired_columns") or 0)
    if paired < 2:
        return [[slot] for slot in slots]
    columns: list[list[dict[str, Any]]] = []
    for slot in slots:
        if columns and abs((slot.get("x_emu") or 0) - (columns[-1][0].get("x_emu") or 0)) <= 20_000:
            columns[-1].append(slot)
        else:
            columns.append([slot])
    for column in columns:
        column.sort(key=lambda slot: (slot.get("y_emu") or 0, slot.get("idx")))
    return columns


def _set_text(placeholder: Any, lines: list[str]) -> None:
    frame = placeholder.text_frame
    frame.text = lines[0] if lines else ""
    for line in lines[1:]:
        paragraph = frame.add_paragraph()
        paragraph.text = line


def _insert_picture(
    placeholder: Any,
    image_path: Path,
    fit_mode: str,
    frame_override: dict[str, int] | None = None,
) -> None:
    if frame_override is not None:
        frame = (
            frame_override["x_emu"],
            frame_override["y_emu"],
            frame_override["w_emu"],
            frame_override["h_emu"],
        )
        fit_mode = "contain"
    else:
        frame = (placeholder.left, placeholder.top, placeholder.width, placeholder.height)
    picture = placeholder.insert_picture(str(image_path))
    if fit_mode != "contain" or any(value is None for value in frame):
        return
    left, top, width, height = frame
    native_width, native_height = picture.image.size
    if not native_width or not native_height:
        return
    scale = min(width / native_width, height / native_height)
    fitted_width = int(native_width * scale)
    fitted_height = int(native_height * scale)
    picture.crop_left = picture.crop_right = picture.crop_top = picture.crop_bottom = 0
    picture.left = left + (width - fitted_width) // 2
    picture.top = top + (height - fitted_height) // 2
    picture.width = fitted_width
    picture.height = fitted_height


def _place_text(
    placeholders: dict[Any, Any],
    slot: dict[str, Any] | None,
    lines: list[str],
    label: str,
    applied: list[str],
) -> None:
    if slot is None or not lines:
        return
    placeholder = placeholders.get(slot.get("idx"))
    if placeholder is None:
        return
    _set_text(placeholder, lines)
    applied.append(f"{label}@idx{slot.get('idx')}")


def _fill_text_slots(
    placeholders: dict[Any, Any],
    layout: dict[str, Any],
    need: dict[str, Any],
    applied: list[str],
) -> None:
    title_slots = _ordered_slots(layout, "title")
    subtitle_slots = _ordered_slots(layout, "subtitle")
    _place_text(
        placeholders,
        title_slots[0] if title_slots else None,
        [need["title"]] if need["title"] else [],
        "title",
        applied,
    )
    _place_text(
        placeholders,
        subtitle_slots[0] if subtitle_slots else None,
        [need["subtitle"]] if need["subtitle"] else [],
        "subtitle",
        applied,
    )

    columns = _content_columns(layout)
    for block, column in zip(need["blocks"], columns):
        heading = str(block.get("heading") or "").strip()
        bullets = list(block.get("bullets") or [])
        if len(column) >= 2 and heading:
            _place_text(placeholders, column[0], [heading], "heading", applied)
            _place_text(placeholders, column[1], bullets, "body", applied)
        else:
            lines = ([heading] if heading else []) + bullets
            _place_text(placeholders, column[0], lines, "body", applied)


def _picture_override(
    layout: dict[str, Any],
    slot: dict[str, Any],
    need: dict[str, Any],
    margin_emu: int,
    occupied: set[int],
) -> tuple[dict[str, int] | None, str]:
    # Brand protection first: a slide-filling slot on a titled slide is cut
    # back to the safe area whatever the picture is. Only if that does not
    # apply does the image's own nature decide, and a diagram then takes
    # the template gutter so it never touches a slide edge.
    override = None
    suffix = ""
    if slot.get("full_bleed") and need["title"]:
        override = safe_picture_rect(layout, slot, margin_emu, occupied)
        suffix = "(inset)" if override is not None else ""
    if override is None and need["image_role"] == "diagram":
        override = gutter_inset(slot, margin_emu)
        suffix = "(gutter)" if override is not None else ""
    return override, suffix


def _fill_picture_slots(
    placeholders: dict[Any, Any],
    layout: dict[str, Any],
    need: dict[str, Any],
    applied: list[str],
    margin_emu: int,
) -> None:
    # Everything this slide actually wrote is off limits for a picture inset.
    occupied = {
        int(label.rsplit("idx", 1)[-1])
        for label in applied
        if "idx" in label and label.rsplit("idx", 1)[-1].isdigit()
    }
    for slot, image in zip(_ordered_slots(layout, "picture"), need["images"]):
        placeholder = placeholders.get(slot.get("idx"))
        image_path = Path(image)
        if placeholder is None:
            continue
        if not image_path.is_file():
            raise ComposerError(f"image not found: {image_path}")
        override, suffix = _picture_override(layout, slot, need, margin_emu, occupied)
        _insert_picture(placeholder, image_path, need["image_fit"], override)
        applied.append(f"picture@idx{slot.get('idx')}{suffix}")


def fill_slide(
    slide: Any,
    layout: dict[str, Any],
    need: dict[str, Any],
    applied: list[str],
    margin_emu: int,
) -> None:
    placeholders = {placeholder.placeholder_format.idx: placeholder for placeholder in slide.placeholders}
    _fill_text_slots(placeholders, layout, need, applied)
    _fill_picture_slots(placeholders, layout, need, applied, margin_emu)
    if need["notes"]:
        slide.notes_slide.notes_text_frame.text = need["notes"]


__all__ = ["drop_sample_slides", "fill_slide", "layout_index"]
