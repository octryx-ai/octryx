"""Trust model v1: the medallion layer is the canonical curation stage. Bronze is raw evidence, silver is validated by a
human approval, gold is an explicit act."""

from __future__ import annotations

from typing import Any

LAYER_GOLD = "gold"
LAYER_SILVER = "silver"
LAYER_BRONZE = "bronze"
_LAYER_RANK = {LAYER_GOLD: 0, LAYER_SILVER: 1, LAYER_BRONZE: 2}


def layer_rank(layer: Any) -> int:
    # Unknown counts as bronze.
    return _LAYER_RANK.get(str(layer or "").strip().lower(), _LAYER_RANK[LAYER_BRONZE])


def promoted_layer_on_review_approval(current_layer: Any, review_status: str) -> str | None:
    # Only a human approval promotes bronze to silver; silver and gold keep their stage.
    if str(review_status or "").strip().lower() != "approved":
        return None
    if str(current_layer or "").strip().lower() == LAYER_BRONZE:
        return LAYER_SILVER
    return None


MULTI_SOURCE_SILVER_THRESHOLD = 2


def evidence_trust_level(current_level: Any, source_refs: Any) -> str:
    # Monotonic: two distinct source refs promote bronze to silver, gold stays explicit, and a level is never demoted.
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
