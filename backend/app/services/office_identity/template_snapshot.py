"""``office_template_snapshot`` — deterministic evidence brief for a template."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..corp_identity.parsing import NS_P
from ..error_facts import error_text
from .layout_usage import (
    USAGE_SOURCE,
    USAGE_SOURCE_EXAMPLE,
    collect_layout_usage,
    collect_layout_usage_from_example,
)
from .package import PRESENTATION_PART, PresentationPackage
from .template_icons import _extract_icons
from .template_layouts import _extract_layouts
from .template_theme import _extract_theme

SNAPSHOT_KIND = "office_template_snapshot"
#: 5 — layouts gained ``icon_anchors``, the static icon holders the composer
#:     fills from the icon catalog;
#: 4 — layouts gained ``usage``, learned from the template's own sample slides;
#: 3 — layouts gained ``origin`` (``template`` vs. normalisation-``derived``);
#: 2 — slots gained ``full_bleed``/``covers``/``slide_area_ratio``/``font_size_pt``.
SNAPSHOT_VERSION = 5

MAX_WARNINGS = 40


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def _slide_size(package: PresentationPackage, warnings: list[str]) -> dict[str, int]:
    presentation = package.presentation()
    node = presentation.find(f"{{{NS_P}}}sldSz") if presentation is not None else None
    if node is None:
        warnings.append("presentation.xml has no slide size")
        return {"width_emu": 0, "height_emu": 0, "type": ""}
    try:
        return {
            "width_emu": int(node.attrib.get("cx", 0)),
            "height_emu": int(node.attrib.get("cy", 0)),
            "type": str(node.attrib.get("type") or "").strip(),
        }
    except (TypeError, ValueError):
        warnings.append("presentation.xml slide size is not numeric")
        return {"width_emu": 0, "height_emu": 0, "type": ""}


def build_template_snapshot(
    template_path: str | Path, *, example_deck_path: str | Path | None = None
) -> dict[str, Any]:
    """Extract the deterministic evidence brief of a PowerPoint template."""
    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"template not found: {path}")
    warnings: list[str] = []
    with PresentationPackage(path) as package:
        if package.presentation() is None:
            raise ValueError(f"not a PowerPoint package (no {PRESENTATION_PART}): {path}")
        master_parts = package.master_parts()
        if not master_parts:
            warnings.append("no slide master found")
        slide_size = _slide_size(package, warnings)
        theme = _extract_theme(package, master_parts, warnings)
        layouts = _extract_layouts(package, master_parts, slide_size, warnings)
        # The template's own slides demonstrate how its layouts are meant to be
        # used. A layout no sample slide uses keeps ``usage: None`` — absence of
        # evidence is recorded as absence, never as a zeroed record.
        usage_by_part = collect_layout_usage(package, layouts)
        usage_source = USAGE_SOURCE
        example_meta = _apply_example_usage(
            layouts, usage_by_part, example_deck_path=example_deck_path, warnings=warnings
        )
        if example_meta is not None:
            usage_source = USAGE_SOURCE_EXAMPLE
        for layout in layouts:
            layout["usage"] = usage_by_part.get(str(layout.get("part")))
        icons = _extract_icons(package, warnings, int(slide_size.get("width_emu") or 0))
        sample_slides = len(package.slide_parts())
        snapshot: dict[str, Any] = {
            "kind": SNAPSHOT_KIND,
            "version": SNAPSHOT_VERSION,
            "source_file": path.name,
            "slide_size": slide_size,
            "theme": theme,
            "masters": [
                {"index": index, "part": part, "theme_part": package.theme_for_master(part) or ""}
                for index, part in enumerate(master_parts, start=1)
            ],
            "layouts": layouts,
            "icons": icons,
            "sample_slides": sample_slides,
            "usage_source": usage_source,
            "summary": _summary(layouts, len(master_parts), icons, len(package.media_parts(".svg"))),
            "warnings": warnings[:MAX_WARNINGS],
        }
        if example_meta is not None:
            snapshot["example_deck"] = example_meta
    return snapshot


def _apply_example_usage(
    layouts: list[dict[str, Any]],
    usage_by_part: dict[str, dict[str, Any]],
    *,
    example_deck_path: str | Path | None,
    warnings: list[str],
) -> dict[str, Any] | None:
    if not example_deck_path:
        return None
    example_path = Path(example_deck_path)
    if not example_path.is_file():
        warnings.append(f"example deck not found: {example_path.name}")
        return None
    try:
        with PresentationPackage(example_path) as example_package:
            example_usage = collect_layout_usage_from_example(example_package, layouts)
            example_slides = len(example_package.slide_parts())
    except (ValueError, OSError) as exc:
        warnings.append(f"example deck could not be read: {error_text('example_deck_unreadable', exc)}")
        return None
    usage_by_part.update(example_usage)
    return {
        "source_file": example_path.name,
        "slides": example_slides,
        "layouts_learned": len(example_usage),
    }


def _summary(
    layouts: list[dict[str, Any]], masters: int, icons: list[dict[str, Any]], svg_media: int
) -> dict[str, Any]:
    return {
        "layout_count": len(layouts),
        "master_count": masters,
        "icon_count": len(icons),
        "svg_media_count": svg_media,
        "shapes": _shape_summary(layouts),
        "layouts_with_usage": sum(1 for layout in layouts if layout.get("usage")),
    }


def _shape_summary(layouts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for layout in layouts:
        shape = str(layout.get("content_shape") or "unknown")
        counts[shape] = counts.get(shape, 0) + 1
    return dict(sorted(counts.items()))


def layouts_by_shape(snapshot: dict[str, Any], content_shape: str) -> list[dict[str, Any]]:
    return [
        layout
        for layout in snapshot.get("layouts", [])
        if layout.get("content_shape") == content_shape
    ]


def layout_by_key(snapshot: dict[str, Any], key: str) -> dict[str, Any] | None:
    for layout in snapshot.get("layouts", []):
        if layout.get("key") == key:
            return layout
    return None


def slots_by_role(layout: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [slot for slot in layout.get("slots", []) if slot.get("role") == role]


def has_full_bleed_picture(layout: dict[str, Any]) -> bool:
    return any(slot.get("full_bleed") for slot in slots_by_role(layout, "picture"))


__all__ = [
    "SNAPSHOT_KIND",
    "SNAPSHOT_VERSION",
    "build_template_snapshot",
    "has_full_bleed_picture",
    "layout_by_key",
    "layouts_by_shape",
    "slots_by_role",
]
