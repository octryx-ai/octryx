"""From slide drafts to plan entries: open points, speaker notes, entries."""

from __future__ import annotations

import math
from typing import Any

from .aws_deck_evidence import MAX_BULLETS_PER_SLIDE, Bullet, SlideDraft, missing_source
from .aws_deck_layout_fit import _fitting_layouts, _pick_layout_key, _pick_shape
from .aws_deck_slides import BULLET_SHAPES

OPEN_POINTS_TITLE = "Open points"


def _open_point_drafts(drafts: list[SlideDraft]) -> list[SlideDraft]:
    seen: set[str] = set()
    points: list[Bullet] = []
    for position, draft in enumerate(drafts, start=1):
        for marker in draft.markers:
            if marker in seen:
                continue
            seen.add(marker)
            points.append(Bullet(marker, f"Slide {position}: {draft.title}"))
    if not points:
        return [
            SlideDraft(
                title=OPEN_POINTS_TITLE,
                source="Planner: no markers produced",
                shape_preference=BULLET_SHAPES,
                bullets=[
                    Bullet(
                        "No open points from the evidence — content approval is still pending",
                        "Planner: no [DECISION]/[SOURCE MISSING]/[CHECK NUMBER] markers",
                    )
                ],
                keep_when_empty=True,
            )
        ]
    chunks = math.ceil(len(points) / MAX_BULLETS_PER_SLIDE)
    result: list[SlideDraft] = []
    for index in range(chunks):
        window = points[index * MAX_BULLETS_PER_SLIDE : (index + 1) * MAX_BULLETS_PER_SLIDE]
        suffix = f" ({index + 1}/{chunks})" if chunks > 1 else ""
        result.append(
            SlideDraft(
                title=f"{OPEN_POINTS_TITLE}{suffix}",
                source="Planner: markers of all slides",
                shape_preference=BULLET_SHAPES,
                bullets=window,
                keep_when_empty=True,
            )
        )
    return result


def _notes(draft: SlideDraft) -> str:
    lines = [f"Slide source: {draft.source}"]
    if draft.subtitle:
        source = draft.subtitle_source or draft.source
        lines.append(f"- Subtitle: {draft.subtitle} | Source: {source}")
    lines.extend(bullet.note_line() for bullet in draft.bullets)
    for block in draft.blocks:
        if block.heading:
            lines.append(f"- Column: {block.heading}")
        lines.extend(bullet.note_line() for bullet in block.bullets)
    lines.extend(draft.markers)
    return "\n".join(lines)


def _resolve_subtitles(drafts: list[SlideDraft], template_snapshot: dict[str, Any]) -> None:
    for draft in drafts:
        if not draft.subtitle:
            continue
        if _fitting_layouts(
            template_snapshot, draft.content_units(), len(draft.images), True, True
        ):
            continue
        draft.markers.append(
            missing_source(
                f"Subtitle placeholder in the template for slide '{draft.title}': {draft.subtitle}"
            )
        )
        draft.subtitle = ""


def _to_entry(draft: SlideDraft, template_snapshot: dict[str, Any]) -> dict[str, Any]:
    units = draft.content_units()
    pictures = len(draft.images)
    shape = _pick_shape(
        template_snapshot,
        draft.shape_preference,
        units,
        pictures,
        bool(draft.title),
        bool(draft.subtitle),
    )
    entry: dict[str, Any] = {"title": draft.title, "notes": _notes(draft)}
    if shape:
        entry["content_shape"] = shape
        layout_key = _pick_layout_key(template_snapshot, draft, shape)
        if layout_key:
            entry["layout_key"] = layout_key
    if draft.subtitle:
        entry["subtitle"] = draft.subtitle
    if draft.blocks:
        entry["blocks"] = [
            {"heading": block.heading, "bullets": [bullet.text for bullet in block.bullets]}
            for block in draft.blocks
        ]
        # Icon holders of an icons_N layout, addressed by column order. The
        # composer resolves each key against the template's icon catalog and
        # places nothing when the template ships no matching icon.
        topic_keys = [block.topic_key for block in draft.blocks]
        if any(topic_keys):
            entry["icon_topics"] = topic_keys
    elif draft.bullets:
        entry["bullets"] = [bullet.text for bullet in draft.bullets]
    if draft.images:
        entry["image_slots"] = list(draft.images)
        entry["image_role"] = draft.image_role or "diagram"
    return entry


__all__ = ["OPEN_POINTS_TITLE", "_notes", "_open_point_drafts", "_resolve_subtitles", "_to_entry"]
