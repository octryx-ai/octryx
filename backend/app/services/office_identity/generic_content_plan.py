"""Compose a deck or document about *any* topic from sourced content."""

from __future__ import annotations

from typing import Any

from .aws_deck_entries import _open_point_drafts, _resolve_subtitles, _to_entry
from .aws_deck_evidence import Bullet, ContentBlock, SlideDraft, check_number, decision, is_marker, missing_source
from .aws_deck_plan import _cap
from .aws_deck_sections import (
    AGENDA_SHAPES,
    SECTION_SHAPES,
    STATEMENT_SHAPES,
    agenda_draft,
    section_draft,
    template_offers,
)
from .aws_deck_slides import BULLET_SHAPES, diagram_drafts
from .aws_deck_title import TITLE_SHAPES

#: Two-column content uses the template's two-box/two-content layouts (clean,
#: no decorative icon holders). Three or four columns fall back to a dense bullet
#: slide rather than an icons-N layout, whose ring holders would stay empty for a
#: general topic (the icon catalog maps AWS topics, not arbitrary headings).
_TWO_COLUMN_SHAPES = ("columns_2", "two_content", "bullets")
_QUOTE_SHAPES = ("quote", "statement", "bullets")
#: A block whose content is at most this long reads as a headline, so it earns a
#: statement slide rather than a single-bullet content slide.
_STATEMENT_MAX_CHARS = 90


def _bullets(raw: Any) -> list[Bullet]:
    bullets: list[Bullet] = []
    for item in raw or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            source = str(item.get("source") or "").strip()
        else:
            text, source = str(item or "").strip(), ""
        if text:
            bullets.append(Bullet(text, source))
    return bullets


def _columns(raw: Any) -> list[tuple[str, str, str]]:
    columns: list[tuple[str, str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or item.get("title") or "").strip()
        text = str(item.get("text") or item.get("body") or "").strip()
        source = str(item.get("source") or "").strip()
        if heading or text:
            columns.append((heading or text, text if heading else "", source))
    return columns


def _section_draft(section: dict[str, Any]) -> SlideDraft | None:
    heading = str(section.get("heading") or "").strip()
    kind = str(section.get("type") or "").strip().lower()
    subtitle = str(section.get("subtitle") or section.get("text") or "").strip()
    source = str(section.get("source") or "").strip()
    bullets = _bullets(section.get("bullets"))
    columns = _columns(section.get("columns"))
    if not heading and not bullets and not columns and not subtitle:
        return None

    if kind == "quote" or (not kind and section.get("quote")):
        text = str(section.get("quote") or subtitle or (bullets[0].text if bullets else heading)).strip()
        quote_source = source or (bullets[0].source if bullets else "")
        return SlideDraft(
            title=text,
            source=quote_source or "user input",
            shape_preference=_QUOTE_SHAPES,
            keep_when_empty=True,
        )

    if columns and kind in {"", "columns"}:
        if len(columns) == 2:
            draft = SlideDraft(title=heading, source=source or "user input", shape_preference=_TWO_COLUMN_SHAPES)
            for column_heading, column_text, column_source in columns:
                block_bullets = [Bullet(column_text, column_source)] if column_text else []
                draft.blocks.append(ContentBlock(heading=column_heading, bullets=block_bullets))
            return draft
        # Three or more: one dense bullet per column ("Heading — text"), clean.
        column_bullets = [Bullet(f"{ch} — {ct}" if ct else ch, cs) for ch, ct, cs in columns]
        return SlideDraft(
            title=heading,
            source=source or "user input",
            shape_preference=BULLET_SHAPES,
            bullets=column_bullets,
        )

    is_headline = not bullets and (subtitle or heading) and len(subtitle or heading) <= _STATEMENT_MAX_CHARS
    if kind == "statement" or (not kind and is_headline):
        title = heading or subtitle
        return SlideDraft(
            title=title,
            source=source or "user input",
            shape_preference=STATEMENT_SHAPES,
            subtitle=subtitle if heading and subtitle != title else "",
            keep_when_empty=True,
        )

    draft = SlideDraft(title=heading, source=source, shape_preference=BULLET_SHAPES, bullets=bullets, subtitle=subtitle)
    if not draft.source and not any(bullet.source for bullet in bullets):
        draft.markers.append(missing_source(f"Section \"{heading}\" without a source"))
    return draft


def _sections(content: dict[str, Any]) -> list[SlideDraft]:
    drafts: list[SlideDraft] = []
    for section in content.get("sections") or []:
        if isinstance(section, dict):
            draft = _section_draft(section)
            if draft is not None:
                drafts.append(draft)
    return drafts


def _title_draft(content: dict[str, Any]) -> SlideDraft:
    draft = SlideDraft(
        title=str(content.get("title") or "Presentation").strip() or "Presentation",
        source=str(content.get("source") or "user input").strip() or "user input",
        shape_preference=TITLE_SHAPES,
        subtitle=str(content.get("subtitle") or "").strip(),
        keep_when_empty=True,
    )
    for point in content.get("open_points") or []:
        text = str(point or "").strip()
        if text:
            draft.markers.append(text if is_marker(text) else check_number(text))
    if not content.get("open_points"):
        draft.markers.append(decision("Confirm the title and audience"))
    return draft


def build_generic_deck_plan(
    content: dict[str, Any],
    template_snapshot: dict[str, Any],
    *,
    diagram_images: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Deck plan for a general topic, composed through the shared deck pipeline."""
    content = content if isinstance(content, dict) else {}
    template_snapshot = template_snapshot if isinstance(template_snapshot, dict) else {}
    images = list(diagram_images or [])

    deck_title = _title_draft(content)
    opening = _headline_draft(content)
    content_drafts = _sections(content)
    diagram_block = diagram_drafts(images) if images else []

    everything = [deck_title, *([opening] if opening else []), *content_drafts, *diagram_block]
    _resolve_subtitles(everything, template_snapshot)
    closing = _open_point_drafts(everything)

    ordered: list[SlideDraft] = [deck_title]
    if opening is not None:
        ordered.append(opening)
    # An agenda earns its slide once the deck has enough distinct sections to
    # need one; a three-section deck reads better without it.
    if len(content_drafts) >= 4 and template_offers(template_snapshot, AGENDA_SHAPES, units=1, subtitle=False):
        ordered.append(agenda_draft([draft.title for draft in content_drafts if draft.title]))

    # Section dividers are dosed: only on a deck large enough for them to
    # structure something, and only every few slides — not before each one.
    dividers = (
        len(content_drafts) >= 5 and template_offers(template_snapshot, SECTION_SHAPES, units=0, subtitle=False)
    )
    for position, draft in enumerate(content_drafts):
        if dividers and position and position % 3 == 0:
            ordered.append(section_draft(draft.title, position + 1))
        ordered.append(draft)
    ordered.extend(diagram_block)
    ordered.extend(closing)

    return [_to_entry(draft, template_snapshot) for draft in _cap(ordered, closing)]


def _headline_draft(content: dict[str, Any]) -> SlideDraft | None:
    raw = content.get("statement")
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    return SlideDraft(
        title=text,
        source=str(raw.get("source") or content.get("source") or "user input"),
        shape_preference=STATEMENT_SHAPES,
        subtitle=str(raw.get("subtitle") or "").strip(),
        keep_when_empty=True,
    )


def _document_section_blocks(section: dict[str, Any]) -> list[dict[str, Any]]:
    heading = str(section.get("heading") or "").strip()
    if not heading:
        return []
    source = str(section.get("source") or "").strip()
    blocks: list[dict[str, Any]] = [{"kind": "heading", "level": 1, "text": heading, "source": source}]
    paragraph = str(section.get("subtitle") or section.get("text") or "").strip()
    if paragraph:
        blocks.append({"kind": "paragraph", "text": paragraph})
    bullets = _bullets(section.get("bullets"))
    columns = _columns(section.get("columns"))
    # Columns become one bullet each ("Heading — text"); a document reads
    # them as a list rather than side-by-side panels.
    for column_heading, column_text, column_source in columns:
        label = f"{column_heading} — {column_text}" if column_text else column_heading
        bullets.append(Bullet(label, column_source))
    if bullets:
        blocks.append({"kind": "bullets", "items": [{"text": b.text, "source": b.source} for b in bullets]})
    if not source and not bullets and not paragraph:
        blocks.append({"kind": "marker", "text": missing_source(f"Section \"{heading}\" without content or source")})
    return blocks


def build_generic_document_plan(
    content: dict[str, Any],
    *,
    diagram_images: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Document plan (kind-based blocks) for a general topic."""
    content = content if isinstance(content, dict) else {}
    images = list(diagram_images or [])
    plan: list[dict[str, Any]] = [
        {
            "kind": "title",
            "text": str(content.get("title") or "Document").strip() or "Document",
            "subtitle": str(content.get("subtitle") or "").strip(),
            "source": str(content.get("source") or "user input").strip(),
        }
    ]

    if images:
        plan.append({"kind": "heading", "level": 1, "text": "Figures", "source": "diagram pipeline"})
        for image in images:
            if isinstance(image, dict):
                plan.append(
                    {
                        "kind": "diagram",
                        "level": 2,
                        "title": str(image.get("title") or "Diagram"),
                        "image": str(image.get("path") or ""),
                        "source": f"Diagram {image.get('diagram_id', '')}",
                    }
                )

    for section in content.get("sections") or []:
        if isinstance(section, dict):
            plan.extend(_document_section_blocks(section))

    plan.append({"kind": "heading", "level": 1, "text": "Open points", "source": "Planner"})
    points = content.get("open_points") or []
    if not points:
        plan.append({"kind": "marker", "text": decision("Confirm the title and audience")})
    for point in points:
        text = str(point or "").strip()
        if text:
            plan.append({"kind": "marker", "text": text if is_marker(text) else check_number(text)})
    return plan


__all__ = ["build_generic_deck_plan", "build_generic_document_plan"]
