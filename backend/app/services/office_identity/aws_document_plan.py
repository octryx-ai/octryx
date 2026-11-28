"""Evidence-bound Word document plan for an AWS architecture report."""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import (
    counts,
    decision,
    int_or_none,
    join_list,
    mapping,
    string_list,
    text,
)
from .aws_deck_labels import resource_phrase
from .aws_deck_themes import OTHER_THEME, theme_buckets

MAX_BULLETS_PER_SECTION = 10
MAX_KNOWLEDGE_FACTS = 12


def _heading(text: str, source: str, *, level: int = 1) -> dict[str, Any]:
    return {"kind": "heading", "level": level, "text": text, "source": source}


def _title_block(account: str, regions: list[str]) -> dict[str, Any]:
    return {
        "kind": "title",
        "text": f"AWS architecture — account {account}" if account else "AWS architecture",
        "subtitle": f"Regions: {join_list(regions)}" if regions else "",
        "source": "account_id, scope.regions",
    }


def _summary_blocks(summary: dict[str, Any]) -> list[dict[str, Any]]:
    node_count = int_or_none(summary.get("resource_node_count"))
    if node_count is None:
        return []
    edge_count = int_or_none(summary.get("edge_count"))
    sentence = f"The survey records {node_count} resources"
    if edge_count is not None:
        sentence += f" and {edge_count} relationships between them"
    sentence += "."
    return [
        _heading("Summary", "service_summary.resource_node_count"),
        {"kind": "paragraph", "text": sentence},
    ]


def _knowledge_blocks(knowledge_facts: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    facts = list(knowledge_facts or [])[:MAX_KNOWLEDGE_FACTS]
    if not facts:
        return []
    return [
        {"kind": "heading", "level": 1, "text": "Knowledge base", "source": "knowledge_search"},
        {
            "kind": "bullets",
            "items": [{"text": fact.get("statement", ""), "source": fact.get("source", "")} for fact in facts],
        },
    ]


def _diagram_blocks(diagram_images: list[Any] | None) -> list[dict[str, Any]]:
    images = list(diagram_images or [])
    if not images:
        return []
    blocks: list[dict[str, Any]] = [_heading("Architecture at a glance", "aws_topology_diagram")]
    for image in images:
        if not isinstance(image, dict):
            continue
        title = str(image.get("title") or "Diagram").strip()
        blocks.append(
            {
                "kind": "diagram",
                "level": 2,
                "title": title,
                "image": str(image.get("path") or ""),
                "source": f"Diagram {image.get('diagram_id', '')} (aws_topology_diagram, rendered as PNG)",
            }
        )
    return blocks


def _resource_blocks(node_counts: dict[str, int]) -> tuple[list[dict[str, Any]], list[str]]:
    unmapped: list[str] = []
    if not node_counts:
        return [], unmapped
    blocks: list[dict[str, Any]] = [_heading("Resources in detail", "service_summary.node_counts_by_type")]
    for theme, entries in theme_buckets(node_counts):
        blocks.append(
            {
                "kind": "heading",
                "level": 2,
                "text": f"{theme} — {len(entries)} {'resource kind' if len(entries) == 1 else 'resource kinds'}",
                "source": "service_summary.node_counts_by_type",
            }
        )
        blocks.append(
            {
                "kind": "bullets",
                "items": [
                    {"text": resource_phrase(node_type, count), "source": "node_counts_by_type"}
                    for node_type, count in entries[:MAX_BULLETS_PER_SECTION]
                ],
            }
        )
        if theme == OTHER_THEME:
            unmapped = [node_type for node_type, _count in entries]
    return blocks, unmapped


def _open_point_blocks(unmapped: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"kind": "heading", "level": 1, "text": "Open points", "source": "Planner"},
        {"kind": "marker", "text": decision("Confirm the document title and audience")},
    ]
    if unmapped:
        blocks.append(
            {
                "kind": "marker",
                "text": decision(f"Theme assignment missing in the catalog for: {join_list(unmapped)}"),
            }
        )
    return blocks


def build_aws_document_plan(
    aws_snapshot: dict[str, Any],
    document_snapshot: dict[str, Any],
    *,
    knowledge_facts: list[dict[str, str]] | None = None,
    diagram_images: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Ordered document blocks; the composer renders each with a template style."""
    del document_snapshot  # the plan is style-agnostic; the composer maps roles.
    snapshot = aws_snapshot if isinstance(aws_snapshot, dict) else {}
    summary = mapping(snapshot.get("service_summary"))
    scope = mapping(snapshot.get("scope"))
    account = text(snapshot.get("account_id"))
    regions = [region for region in (string_list(scope.get("regions")) or [text(snapshot.get("region"))]) if region]
    node_counts = counts(summary.get("node_counts_by_type"))

    plan: list[dict[str, Any]] = [_title_block(account, regions)]
    plan.extend(_summary_blocks(summary))
    plan.extend(_knowledge_blocks(knowledge_facts))
    plan.extend(_diagram_blocks(diagram_images))
    resource_blocks, unmapped = _resource_blocks(node_counts)
    plan.extend(resource_blocks)
    plan.extend(_open_point_blocks(unmapped))
    return plan


__all__ = ["build_aws_document_plan"]
