"""Assembling the deck's blocks: claimed figures, placed facts, dropped slides."""

from __future__ import annotations

from typing import Any

from .aws_deck_evidence import (
    MAX_BULLETS_PER_SLIDE,
    Bullet,
    SlideDraft,
    mapping,
    missing_source,
    text,
)
from .aws_deck_themes import classify_fact_topic


def _claim(draft: SlideDraft, keys: set[str]) -> None:
    draft.bullets = [bullet for bullet in draft.bullets if bullet.key not in keys]


def _distribute_facts(
    facts: list[Any], theme_block: list[SlideDraft]
) -> list[dict[str, str]]:
    by_topic = {draft.topic_key: draft for draft in theme_block if draft.topic_key}
    leftovers: list[dict[str, str]] = []
    for raw in facts:
        fact = mapping(raw)
        statement = text(fact.get("statement"))
        source = text(fact.get("source"))
        if not statement:
            continue
        topic = classify_fact_topic(statement) if source else ""
        target = by_topic.get(topic) if topic else None
        if target is not None and len(target.bullets) < MAX_BULLETS_PER_SLIDE:
            target.bullets.append(Bullet(statement, f"knowledge:{source}"))
            continue
        leftovers.append({"statement": statement, "source": source})
    return leftovers


def _kept(drafts: list[SlideDraft], deck_title: SlideDraft) -> list[SlideDraft]:
    kept: list[SlideDraft] = []
    for draft in drafts:
        if draft.bullets or draft.blocks or draft.images or draft.keep_when_empty:
            kept.append(draft)
        else:
            deck_title.markers.append(
                missing_source(f"Slide '{draft.title}' dropped: no supported statement")
            )
    return kept


__all__ = ["_claim", "_distribute_facts", "_kept"]
