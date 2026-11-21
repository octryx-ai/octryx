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
    """Remove bullets a stronger slide now carries, so nothing is said twice."""
    draft.bullets = [bullet for bullet in draft.bullets if bullet.key not in keys]


def _distribute_facts(
    facts: list[Any], theme_block: list[SlideDraft]
) -> list[dict[str, str]]:
    """Attach each uniquely themed fact to its theme slide; return the rest.

    A fact with a traceable source whose statement classifies to exactly one
    theme *that this deck actually has a slide for* becomes an extra sourced
    bullet on that slide (its note keeps ``| Source: knowledge:<id>``). Every
    other fact — no source, no unique theme, or a theme this deck did not
    build — stays in the returned list for the "Domain context" slide, so
    no fact is ever dropped. Deterministic: facts are processed in order and a
    full theme slide keeps its overflow for the context slide.
    """
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
    """Drop content slides without a single sourced statement — and say so."""
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
