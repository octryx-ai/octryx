"""Staged identity resolution (tier 2, P5).

Deterministic identifiers (connector ids, emails, exact aliases) already merge at
upsert time via the alias table. This module handles the WEAK signals: candidate
pairs (same type, near-identical name or high embedding similarity) become
``KnowledgeMergeProposal`` rows with status ``needs_review`` — never a silent
merge. An approved proposal is applied by ``merge_nodes``, which re-points
edges, aliases, and claims onto the kept node and retires the merged one.
"""

from __future__ import annotations

from .merge import decide_merge_proposal, merge_nodes
from .proposals import _EMBEDDING_SIGNAL, _EMBEDDING_THRESHOLD, _NAME_SIGNAL, _name_key, propose_identity_merges

__all__ = [
    "_EMBEDDING_SIGNAL",
    "_EMBEDDING_THRESHOLD",
    "_NAME_SIGNAL",
    "_name_key",
    "decide_merge_proposal",
    "merge_nodes",
    "propose_identity_merges",
]
