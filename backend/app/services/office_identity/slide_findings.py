"""The finding record, and how a composed slide is read back."""

from __future__ import annotations

from typing import Any

from app.services.office_identity.icon_embedding import ICON_SHAPE_NAME_PREFIX

#: Severities. ``warning`` marks a violation, ``info`` an observation that a
#: human may legitimately accept (see ``empty_content_next_to_picture``).
SEVERITIES = ("info", "warning")


def finding(
    code: str,
    slide_index: int,
    layout_key: str,
    slot_idx: int | None,
    message: str,
    severity: str = "warning",
) -> dict[str, Any]:
    return {
        "code": code,
        "slide_index": slide_index,
        "layout_key": layout_key,
        "slot_idx": slot_idx,
        "severity": severity,
        "message": message,
    }


def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["slide_index"],
        item["code"],
        item["slot_idx"] if item["slot_idx"] is not None else -1,
        item["message"],
    )


def is_picture(shape: Any) -> bool:
    return str(shape._element.tag).endswith("}pic")


def is_template_icon(shape: Any) -> bool:
    try:
        return str(shape.name or "").startswith(ICON_SHAPE_NAME_PREFIX)
    except (AttributeError, TypeError):
        return False


def placeholder_idx(shape: Any) -> int | None:
    try:
        return int(shape.placeholder_format.idx)
    except (AttributeError, TypeError, ValueError):
        return None


def paragraph_texts(shape: Any) -> list[str]:
    if not getattr(shape, "has_text_frame", False):
        return []
    return [
        paragraph.text.strip()
        for paragraph in shape.text_frame.paragraphs
        if paragraph.text.strip()
    ]


def shape_rect(shape: Any) -> dict[str, int] | None:
    values = (shape.left, shape.top, shape.width, shape.height)
    if any(not isinstance(value, int) for value in values):
        return None
    return {"x_emu": values[0], "y_emu": values[1], "w_emu": values[2], "h_emu": values[3]}


def slide_content(slide: Any) -> tuple[dict[int, list[str]], dict[int | None, Any]]:
    texts: dict[int, list[str]] = {}
    pictures: dict[int | None, Any] = {}
    for shape in slide.shapes:
        if is_picture(shape):
            if is_template_icon(shape):
                continue  # brand furniture, not a content picture
            pictures.setdefault(placeholder_idx(shape), shape)
            continue
        index = placeholder_idx(shape)
        lines = paragraph_texts(shape)
        if index is not None and lines:
            texts[index] = lines
    return texts, pictures


def picture_items(pictures: dict[int | None, Any]) -> list[tuple[int | None, Any]]:
    return sorted(pictures.items(), key=lambda item: (item[0] is None, item[0]))


__all__ = [
    "SEVERITIES",
    "finding",
    "is_picture",
    "is_template_icon",
    "paragraph_texts",
    "picture_items",
    "placeholder_idx",
    "shape_rect",
    "slide_content",
    "sort_key",
]
