"""Trust model v1: the medallion layer is THE canonical curation stage.

One model instead of three parallel signals (layer, review_status, graph
trust_level). Rules:

- ``bronze``  - raw ingested evidence (source-derived, never guessed).
- ``silver``  - validated: a human review approval promotes bronze here
  automatically (the approval IS the validation event).
- ``gold``    - curated/consolidated; promotion stays an explicit act
  (consolidation and multi-source confirmation hooks follow in v2).

Consumers rank by layer instead of hard-filtering: everything stays
visible, reliability is explicit on every item.
"""

from __future__ import annotations

from typing import Any

LAYER_GOLD = "gold"
LAYER_SILVER = "silver"
LAYER_BRONZE = "bronze"
_LAYER_RANK = {LAYER_GOLD: 0, LAYER_SILVER: 1, LAYER_BRONZE: 2}


def layer_rank(layer: Any) -> int:
    """Sort key: gold first, unknown treated as bronze."""
    return _LAYER_RANK.get(str(layer or "").strip().lower(), _LAYER_RANK[LAYER_BRONZE])


def promoted_layer_on_review_approval(current_layer: Any, review_status: str) -> str | None:
    """Return the new layer when a review approval promotes the entry.

    A human approval of bronze evidence is the validation event that defines
    silver. Silver/gold entries keep their stage; only 'approved' promotes.
    """
    if str(review_status or "").strip().lower() != "approved":
        return None
    if str(current_layer or "").strip().lower() == LAYER_BRONZE:
        return LAYER_SILVER
    return None


MULTI_SOURCE_SILVER_THRESHOLD = 2


def evidence_trust_level(current_level: Any, source_refs: Any) -> str:
    """Graph trust from evidence: independent multi-source confirmation IS
    the validation event for nodes and edges (no human in the loop needed).

    Deterministic and monotonic: ``>= 2`` distinct source refs promote bronze
    to silver; gold stays an explicit act; an existing level is never demoted
    when sources disappear from a later upsert.
    """
    current = str(current_level or "").strip().lower()
    if current and current not in (LAYER_BRONZE, LAYER_SILVER):
        # gold and foreign levels (e.g. "federated") are explicit acts —
        # evidence counting neither promotes nor demotes them.
        return current
    distinct_sources = {str(ref).strip() for ref in (source_refs or []) if str(ref or "").strip()}
    if len(distinct_sources) >= MULTI_SOURCE_SILVER_THRESHOLD:
        return LAYER_SILVER
    return current or LAYER_BRONZE


__all__ = [
    "LAYER_BRONZE",
    "LAYER_GOLD",
    "LAYER_SILVER",
    "MULTI_SOURCE_SILVER_THRESHOLD",
    "evidence_trust_level",
    "layer_rank",
    "promoted_layer_on_review_approval",
]
