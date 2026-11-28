"""What a deck plan entry needs, and which template layout can hold it."""

from __future__ import annotations

from typing import Any

from .template_snapshot import has_full_bleed_picture, layout_by_key

MAX_ERROR_KEYS = 40


class ComposerError(RuntimeError):
    """A plan entry cannot be satisfied by this template."""


# ---------------------------------------------------------------------------
# plan requirements
# ---------------------------------------------------------------------------


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _entry_blocks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw_blocks = entry.get("blocks")
    if isinstance(raw_blocks, (list, tuple)) and raw_blocks:
        blocks: list[dict[str, Any]] = []
        for raw in raw_blocks:
            if isinstance(raw, dict):
                blocks.append(
                    {
                        "heading": str(raw.get("heading") or "").strip(),
                        "bullets": _as_text_list(raw.get("bullets") or raw.get("text")),
                    }
                )
            else:
                blocks.append({"heading": "", "bullets": _as_text_list(raw)})
        return blocks
    bullets = _as_text_list(entry.get("bullets"))
    return [{"heading": "", "bullets": bullets}] if bullets else []


IMAGE_FIT_MODES = frozenset({"contain", "cover"})

#: What the image *is*, which decides whether the template's bleed applies.
#: ``photo`` brings its own border, so a slot that runs off the page edge is
#: the intended look and the template geometry is used unchanged. ``diagram``
#: carries content up to its own border and gets the template gutter as a
#: margin, so no box ends up glued to the slide edge.
IMAGE_ROLES = frozenset({"diagram", "photo"})

#: Absent ``image_role`` keeps the template in charge — never a silent change
#: to how existing plans render.
DEFAULT_IMAGE_ROLE = "photo"


def entry_requirements(entry: dict[str, Any]) -> dict[str, Any]:
    blocks = _entry_blocks(entry)
    fit_mode = str(entry.get("image_fit") or "contain").strip()
    if fit_mode not in IMAGE_FIT_MODES:
        raise ComposerError(
            f"image_fit {fit_mode!r} is not supported; use one of {sorted(IMAGE_FIT_MODES)}"
        )
    image_role = str(entry.get("image_role") or DEFAULT_IMAGE_ROLE).strip()
    if image_role not in IMAGE_ROLES:
        raise ComposerError(
            f"image_role {image_role!r} is not supported; use one of {sorted(IMAGE_ROLES)}"
        )
    return {
        "image_fit": fit_mode,
        "image_role": image_role,
        "blocks": blocks,
        "units": len(blocks),
        "pictures": len(_as_text_list(entry.get("image_slots"))),
        "title": str(entry.get("title") or "").strip(),
        "subtitle": str(entry.get("subtitle") or "").strip(),
        "notes": str(entry.get("notes") or "").strip(),
        "images": _as_text_list(entry.get("image_slots")),
        # Closed topic keys for this slide's icon holders, by column order.
        "icon_topics": [str(key or "").strip() for key in (entry.get("icon_topics") or [])],
    }


# ---------------------------------------------------------------------------
# layout selection
# ---------------------------------------------------------------------------


def _available_keys(snapshot: dict[str, Any]) -> str:
    keys = [str(layout.get("key")) for layout in snapshot.get("layouts", [])]
    shown = keys[:MAX_ERROR_KEYS]
    tail = f" (+{len(keys) - len(shown)} more)" if len(keys) > len(shown) else ""
    return ", ".join(shown) + tail


def _fits(layout: dict[str, Any], need: dict[str, Any]) -> bool:
    capacity = layout.get("capacity") or {}
    if need["units"] > int(capacity.get("content_units") or 0):
        return False
    if need["pictures"] > int(capacity.get("picture_slots") or 0):
        return False
    if need["title"] and not int(capacity.get("title_slots") or 0):
        return False
    if need["subtitle"] and not int(capacity.get("subtitle_slots") or 0):
        return False
    return True


def _avoids_full_bleed(need: dict[str, Any]) -> bool:
    return bool(need["pictures"] and need["title"])


def _rank(layout: dict[str, Any], need: dict[str, Any]) -> tuple[int, ...]:
    capacity = layout.get("capacity") or {}
    content_surplus = int(capacity.get("content_units") or 0) - need["units"]
    picture_surplus = int(capacity.get("picture_slots") or 0) - need["pictures"]
    return (
        1 if (_avoids_full_bleed(need) and has_full_bleed_picture(layout)) else 0,
        # Total surplus first: a 10-picture grid is not a tighter fit for one
        # diagram than a content/picture split just because it has no body slot.
        content_surplus + picture_surplus,
        content_surplus,
        picture_surplus,
        int(layout.get("master_index") or 0),
        len(layout.get("slots") or ()),
        int(layout.get("order") or 0),
    )


def select_layout(
    snapshot: dict[str, Any], entry: dict[str, Any], need: dict[str, Any]
) -> dict[str, Any]:
    requested_key = str(entry.get("layout_key") or "").strip()
    if requested_key:
        layout = layout_by_key(snapshot, requested_key)
        if layout is None:
            raise ComposerError(
                f"layout_key {requested_key!r} is not in this template. "
                f"Available layout keys: {_available_keys(snapshot)}"
            )
        if not _fits(layout, need):
            raise ComposerError(
                f"layout {requested_key!r} ({layout.get('content_shape')}) cannot hold "
                f"{need['units']} content unit(s) and {need['pictures']} picture(s); "
                f"its capacity is {layout.get('capacity')}"
            )
        return layout

    candidates = list(snapshot.get("layouts", []))
    requested_shape = str(entry.get("content_shape") or "").strip()
    if requested_shape:
        candidates = [
            layout for layout in candidates if layout.get("content_shape") == requested_shape
        ]
        if not candidates:
            shapes = sorted({str(item.get("content_shape")) for item in snapshot.get("layouts", [])})
            raise ComposerError(
                f"no layout with content_shape {requested_shape!r} in this template. "
                f"Available shapes: {', '.join(shapes)}"
            )
    fitting = [layout for layout in candidates if _fits(layout, need)]
    if not fitting:
        raise ComposerError(
            f"no layout in this template can hold {need['units']} content unit(s), "
            f"{need['pictures']} picture(s)"
            f"{', a title' if need['title'] else ''}"
            f"{', a subtitle' if need['subtitle'] else ''}. "
            f"Available layout keys: {_available_keys(snapshot)}"
        )
    fitting.sort(key=lambda layout: (*_rank(layout, need), str(layout.get("key"))))
    return fitting[0]


__all__ = [
    "ComposerError",
    "entry_requirements",
    "select_layout",
]
