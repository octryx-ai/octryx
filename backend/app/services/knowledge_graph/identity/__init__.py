"""Staged identity resolution of weak signals into ``needs_review`` merge proposals."""

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
