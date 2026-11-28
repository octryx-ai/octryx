"""Knowledge-graph store: alias-based entity resolution, edges, and claims."""

from __future__ import annotations

from .aliases import (
    _ensure_aliases,
    _node_aliases,
    _project_filter,
    _project_scope,
    normalize_alias,
    resolve_node_by_alias,
)
from .claims import add_claim, get_claims_for_node, replace_claims_of_type
from .descriptions import _MAX_DESCRIPTION_CHARS, _embed_text_for, merge_descriptions, resummarize_node_description
from .edges import get_neighbors, upsert_edge
from .nodes import upsert_node

__all__ = [
    "_MAX_DESCRIPTION_CHARS",
    "_embed_text_for",
    "_ensure_aliases",
    "_node_aliases",
    "_project_filter",
    "_project_scope",
    "add_claim",
    "get_claims_for_node",
    "get_neighbors",
    "merge_descriptions",
    "normalize_alias",
    "replace_claims_of_type",
    "resolve_node_by_alias",
    "resummarize_node_description",
    "upsert_edge",
    "upsert_node",
]
