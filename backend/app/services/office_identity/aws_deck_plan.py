"""Turn an AWS topology snapshot into a deterministic deck plan.

Three binding construction rules:

1. **Every statement comes from evidence.** Titles and bullets are derived from
   concrete fields of the ``aws_topology_snapshot``; nothing here writes a
   sentence that cannot be pointed back at a field.
2. **The source travels with the slide.** The speaker notes list every bullet
   together with the field it came from — no source, no bullet.
3. **The remaining 20 % is made visible.** Wherever evidence is missing or a
   human has to decide, the planner emits an explicit marker into the notes
   *and* repeats it on a closing "Open points" slide.

The diagrams come from our own pipeline: ``diagram_images`` are already
rendered PNGs, this module only places them into image slots. It never renders.

Slide order is fixed and documented (``SLIDE_ORDER``); the same input therefore
always yields the same plan.

The deck is assembled as a presentation, not as a list: a title, an agenda, a
statement slide for the central figure, three equal-rank figures, and section
headers between the blocks. Each of those exists only where the template
carries a layout for it — see ``aws_deck_sections``.
"""

from __future__ import annotations

from typing import Any

from .aws_deck_blocks import _claim, _distribute_facts, _kept
from .aws_deck_coverage import coverage_draft
from .aws_deck_entries import _open_point_drafts, _resolve_subtitles, _to_entry
from .aws_deck_evidence import (
    SlideDraft,
    mapping,
    missing_source,
)
from .aws_deck_layout_fit import place_title_date
from .aws_deck_sections import (
    AGENDA_SHAPES,
    SECTION_SHAPES,
    STATEMENT_SHAPES,
    TOPICS_SHAPES,
    agenda_draft,
    section_draft,
    statement_draft,
    template_offers,
    topics_draft,
)
from .aws_deck_slides import diagram_drafts, knowledge_draft, overview_draft, theme_drafts
from .aws_deck_title import TITLE_SHAPES, title_draft

#: The documented, fixed structure of every deck this planner produces.
SLIDE_ORDER = (
    "title",
    "agenda",
    "statement",
    "topics",
    "overview",
    "coverage",
    "diagrams",
    "themes",
    "knowledge",
    "open_points",
)

#: The blocks the agenda announces and the section headers separate, in order.
SECTION_TITLES = (
    "Survey scope",
    "Architecture at a glance",
    "Resources in detail",
    "Context and open points",
)

#: Structure dosing. A section header exists to separate two *blocks of
#: content*; on a thin deck it separates almost nothing and reads as padding
#: (three dividers for sixteen slides is too many). So dividers are
#: earned twice over: the deck as a whole must reach ``MIN_DECK_CONTENT_SLIDES``
#: content slides, and the block the divider introduces must itself hold at
#: least ``MIN_BLOCK_SLIDES_FOR_DIVIDER``. Neither threshold met ⇒ no divider,
#: and the block simply follows the previous one.
MIN_DECK_CONTENT_SLIDES = 8
MIN_BLOCK_SLIDES_FOR_DIVIDER = 2

#: Hard ceiling on the plan. Structure slides must never push evidence slides
#: out of a deck, so the cap is generous and only ever trims the *middle*; the
#: title and the open-points slides are kept unconditionally.
MAX_DECK_SLIDES = 40


def _cap(ordered: list[SlideDraft], closing: list[SlideDraft]) -> list[SlideDraft]:
    """Bound the deck without ever dropping the honesty balance.

    The open-points slides are the deck's admitted gaps; trimming them to fit a
    slide budget would hide exactly what this planner exists to show. So the
    cap trims the middle and keeps the closing slides.
    """
    if len(ordered) <= MAX_DECK_SLIDES:
        return ordered
    room = max(MAX_DECK_SLIDES - len(closing), 1)
    head = [draft for draft in ordered if draft not in closing][:room]
    return head + closing[: MAX_DECK_SLIDES - len(head)]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _scope_block(
    aws_snapshot: dict[str, Any], summary: dict[str, Any], scope: dict[str, Any],
    template_snapshot: dict[str, Any],
) -> list[SlideDraft]:
    """Statement, topics, overview and coverage — whichever the template carries.

    Emphasis slides claim their figures from the overview so no number is
    stated twice; whatever the template cannot carry simply stays a bullet.
    """
    overview = overview_draft(aws_snapshot, summary, scope)
    block: list[SlideDraft] = []
    statement = statement_draft(aws_snapshot, summary)
    if statement is not None and template_offers(
        template_snapshot, STATEMENT_SHAPES, units=0, subtitle=bool(statement.subtitle)
    ):
        block.append(statement)
        _claim(overview, {"node_count", "edge_count"})
    topics = topics_draft(aws_snapshot, summary, scope)
    if topics is not None and template_offers(
        template_snapshot, TOPICS_SHAPES, units=len(topics.blocks), subtitle=False
    ):
        block.append(topics)
        _claim(overview, {"type_count", "regions", "services"})
    # An overview whose every figure now sits on a stronger slide is dropped as
    # a structural decision, not as missing evidence — hence no marker.
    if overview.bullets:
        block.append(overview)
    block.append(coverage_draft(summary, aws_snapshot))
    return block


def _arranged(
    deck_title: SlideDraft,
    blocks: list[tuple[str, list[SlideDraft]]],
    template_snapshot: dict[str, Any],
) -> list[SlideDraft]:
    """Title, agenda, then the blocks with a divider wherever one is earned."""
    filled = [(title, drafts) for title, drafts in blocks if drafts]
    ordered: list[SlideDraft] = [deck_title]
    if len(filled) > 1 and template_offers(
        template_snapshot, AGENDA_SHAPES, units=1, subtitle=False
    ):
        ordered.append(agenda_draft([title for title, _drafts in filled]))
    section_available = template_offers(
        template_snapshot, SECTION_SHAPES, units=0, subtitle=False
    )
    # Dosing: dividers only on a deck large enough for them to structure
    # something. A small deck reads better as a plain sequence than as a run of
    # near-empty section headers.
    total_content = sum(len(drafts) for _title, drafts in filled)
    dividers_enabled = section_available and total_content >= MIN_DECK_CONTENT_SLIDES
    for position, (title, drafts) in enumerate(filled):
        # No header before the first block: the title slide and the agenda have
        # just opened it, and a divider there would divide nothing. Beyond that,
        # a divider is only worth its slide when the block it introduces holds
        # at least two content slides.
        if position and dividers_enabled and len(drafts) >= MIN_BLOCK_SLIDES_FOR_DIVIDER:
            ordered.append(section_draft(title, position + 1))
        ordered.extend(drafts)
    return ordered


def build_aws_deck_plan(
    aws_snapshot: dict[str, Any],
    template_snapshot: dict[str, Any],
    *,
    knowledge_facts: list[Any] | None = None,
    diagram_images: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a deterministic, evidence-bound deck plan.

    ``aws_snapshot`` is an ``aws_topology_snapshot`` result, ``template_snapshot``
    an ``office_template_snapshot``. ``diagram_images`` are already rendered PNGs
    (``{"path", "title", "diagram_id"}`` or a bare path); this function places
    them, it never renders. ``knowledge_facts`` are ``{"statement", "source"}``
    pairs — without a source a fact becomes a marker, never a sentence.
    """
    aws_snapshot = mapping(aws_snapshot)
    template_snapshot = mapping(template_snapshot)
    summary = mapping(aws_snapshot.get("service_summary"))
    scope = mapping(aws_snapshot.get("scope"))
    images = list(diagram_images or [])

    # The title slide always survives, so it is the one place where a
    # deck-wide gap marker can never be lost with the slide that carries it.
    deck_title = title_draft(aws_snapshot, scope)
    place_title_date(deck_title, template_snapshot, TITLE_SHAPES)
    scope_block = _scope_block(aws_snapshot, summary, scope, template_snapshot)
    diagram_block = diagram_drafts(images) if images else []
    if not images:
        deck_title.markers.append(
            missing_source("Diagram PNG from the AWS diagram pipeline — none supplied")
        )
    theme_block = theme_drafts(summary)
    # Knowledge facts strengthen the theme slides they clearly belong to; only
    # the ones without a unique theme fall back to their own context slide.
    context_block: list[SlideDraft] = []
    if knowledge_facts:
        leftover_facts = _distribute_facts(list(knowledge_facts), theme_block)
        if leftover_facts:
            context_block.append(knowledge_draft(leftover_facts))
    else:
        deck_title.markers.append(
            missing_source("Knowledge context — knowledge_facts empty, no substitute text inserted")
        )
    blocks = [
        (title, _kept(drafts, deck_title))
        for title, drafts in zip(SECTION_TITLES, (scope_block, diagram_block, theme_block, context_block))
    ]
    content = [deck_title] + [draft for _title, drafts in blocks for draft in drafts]
    # Subtitles the template cannot carry are resolved *before* the open points
    # are collected, so the resulting marker still reaches the closing slide.
    _resolve_subtitles(content, template_snapshot)
    closing = _open_point_drafts(content)
    # The open points close the deck, appended to the last block that exists so
    # they always sit behind a section header rather than adrift.
    last = max((index for index, (_t, drafts) in enumerate(blocks) if drafts), default=len(blocks) - 1)
    blocks[last][1].extend(closing)
    ordered = _arranged(deck_title, blocks, template_snapshot)
    return [_to_entry(draft, template_snapshot) for draft in _cap(ordered, closing)]


__all__ = [
    "SLIDE_ORDER",
    "_cap",
    "build_aws_deck_plan",
]
