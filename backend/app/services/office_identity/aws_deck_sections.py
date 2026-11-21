"""The presentation *arc*: agenda, section headers, statement, three topics.

A plain plan produces a correct deck that reads like a report: title, then eleven bullet
slides. A template that ships dozens of layouts, and whose own sample slides use
many of them, is telling us something the planner ignored — a deck has an opening
figure, an agenda, and headers that separate one block of thought from the
next.

Every slide here is optional in exactly the same way: it exists only if the
template offers a layout that can carry it. There is no drawn substitute and no
forced fallback onto a bullet layout that would then render half empty — a
template without a section layout simply gets a deck without section headers,
and the deck stays correct.

The evidence rule is unchanged: these slides carry no claim that is not already
sourced from the snapshot.
"""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import (
    Bullet,
    ContentBlock,
    SlideDraft,
    counts,
    int_or_none,
    join_list,
    mapping,
    string_list,
    text,
)
from .picture_safe_area import title_is_legible

#: Fallback chains. The first shape the template can actually carry wins; if it
#: carries none of them, the slide is dropped rather than approximated.
SECTION_SHAPES = ("section", "title_and_subtitle", "title_only")
AGENDA_SHAPES = ("agenda", "bullets")
STATEMENT_SHAPES = ("statement", "title_and_subtitle")
#: Three equal-rank columns: with an icon holder per column where the template
#: draws them, otherwise the plain three-column (heading over body) layout.
TOPICS_SHAPES = ("icons_3", "columns_3")

#: Exactly three — a three-column topic layout is designed for three
#: equal-rank statements.
TOPIC_COUNT = 3

AGENDA_TITLE = "Agenda"


# ---------------------------------------------------------------------------
# can the template carry this shape at all?
# ---------------------------------------------------------------------------


def template_offers(
    template_snapshot: dict[str, Any], shapes: tuple[str, ...], *, units: int, subtitle: bool
) -> bool:
    """True when some layout of one of these shapes can hold the slide.

    Checked against capacity, never against layout names — the same rule the
    rest of the planner follows. Legibility counts as capacity: a layout that
    would render its title invisible cannot carry a titled slide, so it does
    not make its shape "available" either.
    """
    for layout in template_snapshot.get("layouts") or ():
        if not isinstance(layout, dict) or text(layout.get("content_shape")) not in shapes:
            continue
        capacity = mapping(layout.get("capacity"))
        if units > int(capacity.get("content_units") or 0):
            continue
        if not int(capacity.get("title_slots") or 0):
            continue
        if subtitle and not int(capacity.get("subtitle_slots") or 0):
            continue
        if not title_is_legible(layout):
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# section headers and agenda
# ---------------------------------------------------------------------------


def section_draft(title: str, position: int) -> SlideDraft:
    """A divider slide. It carries the section name and nothing else.

    No subtitle: there is no sourced sentence to put there, and the planner
    does not write one to make the layout look fuller.
    """
    return SlideDraft(
        title=title,
        source=f"Planner: section {position} of this deck",
        shape_preference=SECTION_SHAPES,
        keep_when_empty=True,
    )


def divider_layout_key(template_snapshot: dict[str, Any]) -> str:
    """A section layout that visibly interrupts the flow, if the template has one.

    Corporate templates often ship two: a plain section header (dark title on the
    same plain background the content slides use) and a variant that paints the
    brand backdrop behind a light title. Both are legible, so the gate is silent, and template order puts
    the plain one first — which rendered a divider that divides nothing.

    The rule is structural rather than decorative: a divider exists to separate
    two blocks of content slides, so a layout painting its own backdrop does
    the job and one sharing the content background does not. When no section
    layout paints a backdrop, this returns ``""`` and the template's own order
    decides.
    """
    for layout in template_snapshot.get("layouts") or ():
        if not isinstance(layout, dict) or text(layout.get("content_shape")) != "section":
            continue
        if layout.get("has_background") and title_is_legible(layout):
            return text(layout.get("key"))
    return ""


def agenda_draft(section_titles: list[str]) -> SlideDraft:
    """The deck's own table of contents — sourced from the deck's structure."""
    draft = SlideDraft(
        title=AGENDA_TITLE,
        source="Planner: sections of this deck",
        shape_preference=AGENDA_SHAPES,
        keep_when_empty=True,
    )
    for position, title in enumerate(section_titles, start=1):
        draft.bullets.append(Bullet(title, f"Planner: section {position}"))
    return draft


# ---------------------------------------------------------------------------
# the central figure
# ---------------------------------------------------------------------------


def statement_draft(aws_snapshot: dict[str, Any], summary: dict[str, Any]) -> SlideDraft | None:
    """One slide, one number: how much architecture was actually found.

    Returns ``None`` when the snapshot does not state that number — an empty
    statement slide would be the loudest possible way to say nothing.
    """
    node_count = int_or_none(summary.get("resource_node_count"))
    if node_count is None:
        return None
    edge_count = int_or_none(summary.get("edge_count"))
    account_id = text(aws_snapshot.get("account_id"))

    if edge_count is not None:
        subtitle = f"and {edge_count} relationships between them"
        subtitle_source = "service_summary.edge_count"
    elif account_id:
        subtitle = f"in account {account_id}"
        subtitle_source = "account_id"
    else:
        subtitle = ""
        subtitle_source = ""

    return SlideDraft(
        title=f"{node_count} resources recorded",
        source="service_summary.resource_node_count",
        shape_preference=STATEMENT_SHAPES,
        subtitle=subtitle,
        subtitle_source=subtitle_source,
        keep_when_empty=True,
    )


# ---------------------------------------------------------------------------
# three equal-rank core statements
# ---------------------------------------------------------------------------


def topics_draft(
    aws_snapshot: dict[str, Any], summary: dict[str, Any], scope: dict[str, Any]
) -> SlideDraft | None:
    """Three figures of equal rank, one per column.

    Each column is a number and what it counts — the heading carries the
    figure, the line under it says what it measures. Built only when all three
    figures exist; the layout has three columns and the planner does not leave
    one of them empty.
    """
    regions = string_list(scope.get("regions")) or [text(aws_snapshot.get("region"))]
    regions = [region for region in regions if region]
    node_counts = counts(summary.get("node_counts_by_type"))
    services = string_list(summary.get("inventory_services_with_resources"))

    candidates: list[tuple[str, str, str, str]] = []
    if node_counts:
        candidates.append(
            (
                str(len(node_counts)),
                "distinct resource types",
                "service_summary.node_counts_by_type",
                "resource_types",
            )
        )
    if services:
        candidates.append(
            (
                str(len(services)),
                "AWS services with resources",
                "service_summary.inventory_services_with_resources",
                "services",
            )
        )
    if regions:
        candidates.append(
            (str(len(regions)), f"Regions: {join_list(regions)}", "scope.regions", "regions")
        )

    if len(candidates) < TOPIC_COUNT:
        return None

    draft = SlideDraft(
        title="The survey in three numbers",
        source="service_summary, scope",
        shape_preference=TOPICS_SHAPES,
        keep_when_empty=True,
    )
    for figure, meaning, source, topic_key in candidates[:TOPIC_COUNT]:
        draft.blocks.append(
            ContentBlock(heading=figure, bullets=[Bullet(meaning, source)], topic_key=topic_key)
        )
    return draft


__all__ = [
    "AGENDA_SHAPES",
    "AGENDA_TITLE",
    "SECTION_SHAPES",
    "STATEMENT_SHAPES",
    "TOPICS_SHAPES",
    "TOPIC_COUNT",
    "agenda_draft",
    "section_draft",
    "statement_draft",
    "template_offers",
    "topics_draft",
]
