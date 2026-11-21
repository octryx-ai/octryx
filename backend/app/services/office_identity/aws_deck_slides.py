"""The evidence-to-slide rules of the AWS deck planner.

One function per section of the deck (key figures, diagram slides, themed
resource slides, knowledge context; the title is in ``aws_deck_title``, the
collection coverage in ``aws_deck_coverage``). Each returns a
``SlideDraft``: a slide before a layout is chosen for it, with every bullet
already paired to the snapshot field it came from and every gap already turned
into an explicit marker. Ordering and layout choice live in ``aws_deck_plan``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .aws_deck_evidence import (
    MAX_BULLETS_PER_SLIDE,
    Bullet,
    SlideDraft,
    check_number,
    counts,
    decision,
    int_or_none,
    join_list,
    mapping,
    missing_source,
    string_list,
    text,
)
from .aws_deck_labels import resource_phrase
from .aws_deck_themes import OTHER_THEME, THEME_TOPIC_KEYS, theme_buckets

#: Layout shapes to try, in order. Only shapes the template offers and that can
#: hold the slide are used; otherwise the composer decides on capacity alone.
#: Layout *names* are never inspected here.
BULLET_SHAPES = ("bullets",)
DIAGRAM_SHAPES = ("diagram_full", "content_with_picture")


def _add_scope_bullets(
    draft: SlideDraft, aws_snapshot: dict[str, Any], summary: dict[str, Any], scope: dict[str, Any]
) -> None:
    """Regions, services with resources and the number of resource types."""
    regions = string_list(scope.get("regions")) or [text(aws_snapshot.get("region"))]
    regions = [region for region in regions if region]
    if regions:
        draft.bullets.append(
            Bullet(f"Regions: {join_list(regions)}", "scope.regions", key="regions")
        )

    with_resources = string_list(summary.get("inventory_services_with_resources"))
    if with_resources:
        draft.bullets.append(
            Bullet(
                f"Services with resources: {join_list(with_resources)}",
                "service_summary.inventory_services_with_resources",
                key="services",
            )
        )

    node_counts = counts(summary.get("node_counts_by_type"))
    if node_counts:
        draft.bullets.append(
            Bullet(
                f"{len(node_counts)} distinct resource types",
                "service_summary.node_counts_by_type",
                key="type_count",
            )
        )


def overview_draft(
    aws_snapshot: dict[str, Any], summary: dict[str, Any], scope: dict[str, Any]
) -> SlideDraft:
    draft = SlideDraft(
        title="Overview and key figures",
        source="service_summary",
        shape_preference=BULLET_SHAPES,
    )
    node_count = int_or_none(summary.get("resource_node_count"))
    edge_count = int_or_none(summary.get("edge_count"))
    # The ``key`` marks a bullet the deck may promote to a statement or an
    # icons slide; it is then removed here so no figure is stated twice.
    if node_count is not None:
        draft.bullets.append(
            Bullet(
                f"{node_count} resources recorded",
                "service_summary.resource_node_count",
                key="node_count",
            )
        )
    if edge_count is not None:
        draft.bullets.append(
            Bullet(f"{edge_count} relationships recorded", "service_summary.edge_count", key="edge_count")
        )

    _add_scope_bullets(draft, aws_snapshot, summary, scope)

    max_nodes = int_or_none(scope.get("max_nodes"))
    if node_count is not None and max_nodes is not None and node_count >= max_nodes:
        draft.markers.append(
            check_number(
                f"Node count {node_count} reaches the limit scope.max_nodes={max_nodes} — "
                "the inventory may be truncated"
            )
        )
    if not draft.bullets:
        draft.markers.append(missing_source("service_summary key figures in the aws_topology_snapshot"))
    return draft


def diagram_drafts(diagram_images: list[Any]) -> list[SlideDraft]:
    drafts: list[SlideDraft] = []
    for raw in diagram_images:
        if isinstance(raw, dict):
            path = text(raw.get("path") or raw.get("image_path"))
            title = text(raw.get("title"))
            diagram_id = text(raw.get("diagram_id") or raw.get("id"))
        else:
            path = text(raw)
            title = ""
            diagram_id = ""
        if not path:
            continue
        stem = Path(path).stem
        diagram_id = diagram_id or stem
        draft = SlideDraft(
            title=title or stem,
            source=f"Diagram {diagram_id} (aws_topology_diagram, rendered as PNG)",
            shape_preference=DIAGRAM_SHAPES,
            images=[path],
            image_role="diagram",
            keep_when_empty=True,
        )
        if not title:
            draft.markers.append(
                missing_source(f"Title for diagram {diagram_id} — file name used as a placeholder")
            )
        drafts.append(draft)
    return drafts


def theme_drafts(summary: dict[str, Any]) -> list[SlideDraft]:
    """One slide per theme, written as statements rather than as a field dump.

    ``subnet: 9`` names a snapshot key and a number and leaves the reader to do
    the interpreting. ``9 subnets`` says the same thing in the reader's
    words, and the slide title states how many resource kinds the theme
    holds. Both use only what the snapshot states or the size of what it lists
    (``aws_deck_labels.permitted_numbers``); no share, no sum, no adjective.
    """
    node_counts = counts(summary.get("node_counts_by_type"))
    drafts: list[SlideDraft] = []
    for theme, entries in theme_buckets(node_counts):
        kinds = len(entries)
        noun = "resource kind" if kinds == 1 else "resource kinds"
        draft = SlideDraft(
            title=f"{theme} — {kinds} {noun}",
            source="service_summary.node_counts_by_type",
            shape_preference=BULLET_SHAPES,
            topic_key=THEME_TOPIC_KEYS.get(theme, ""),
        )
        shown = entries[:MAX_BULLETS_PER_SLIDE]
        for node_type, count in shown:
            draft.bullets.append(
                Bullet(
                    resource_phrase(node_type, count),
                    f"service_summary.node_counts_by_type.{node_type}",
                )
            )
        if len(entries) > len(shown):
            hidden = [node_type for node_type, _ in entries[len(shown) :]]
            draft.markers.append(
                check_number(
                    f"{len(hidden)} more types in '{theme}' do not fit on the slide: {join_list(hidden)}"
                )
            )
        if theme == OTHER_THEME:
            draft.markers.append(
                decision(
                    "Theme assignment missing in the catalog for: "
                    + join_list([node_type for node_type, _ in entries])
                )
            )
        drafts.append(draft)
    return drafts


def knowledge_draft(knowledge_facts: list[Any]) -> SlideDraft:
    draft = SlideDraft(
        title="Domain context",
        source="knowledge_facts",
        shape_preference=BULLET_SHAPES,
    )
    for raw in knowledge_facts:
        fact = mapping(raw)
        statement = text(fact.get("statement"))
        source = text(fact.get("source"))
        if not statement:
            continue
        if not source:
            draft.markers.append(missing_source(f"Knowledge fact without a source: {statement}"))
            continue
        draft.bullets.append(Bullet(statement, f"knowledge:{source}"))
    if len(draft.bullets) > MAX_BULLETS_PER_SLIDE:
        hidden = draft.bullets[MAX_BULLETS_PER_SLIDE:]
        draft.bullets = draft.bullets[:MAX_BULLETS_PER_SLIDE]
        draft.markers.append(
            check_number(f"{len(hidden)} more knowledge facts do not fit on the slide")
        )
    # A context slide that carries only a marker (every usable fact went to a
    # theme slide, and what is left is a sourceless fact) must still survive:
    # dropping it would take its [SOURCE MISSING] marker down with it, hiding
    # exactly the gap the deck is supposed to expose.
    if draft.markers and not draft.bullets:
        draft.keep_when_empty = True
    return draft


__all__ = ["BULLET_SHAPES", "DIAGRAM_SHAPES", "diagram_drafts", "knowledge_draft", "overview_draft", "theme_drafts"]
