"""The typed self-check of a change-record extraction, and the guard that enforces it (typing v2).

Graphiti's fact extraction answers with a fixed schema (``ExtractedEdges``): a relation type and a
fact per edge, no field of ours. For a change-record episode the governed model client asks for
that same answer with one more typed field per fact, ``states_version_change``, in the *same*
call: the model sees the source text while it answers, and no extra model call is spent.

The guard is then deterministic and reads only that typed answer, never the words of a fact:

- a fact with a change type whose self-check is ``false`` keeps its text but loses the type
  (its relation becomes :data:`~.change_types.NOT_A_CHANGE_RELATION`);
- a relation that is a change type in another spelling (``replaced_by``, ``REPLACED BY``) is
  written in its canonical form, so the closed set is matched exactly;
- every other relation (the model's own descriptive predicates) is left as it is.

The answer handed back to Graphiti has its own schema again. The self-check field is required: an
answer without it fails validation and is resampled, like any other answer that does not fit.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from pydantic import BaseModel, Field

from .change_types import CHANGE_EDGE_TYPES, NOT_A_CHANGE_RELATION
from .graphiti_boundary import Edge, ExtractedEdges

# The prompt name Graphiti 0.30.2 passes for fact extraction (``utils/maintenance/edge_operations``);
# the contract test runs Graphiti's real ``extract_edges`` to pin it.
EDGE_PROMPT = "extract_edges.edge"
GRAPHITI_EDGE_ANSWER = ExtractedEdges
SELF_CHECK_FIELD = "states_version_change"


class CheckedEdge(Edge):
    states_version_change: bool = Field(
        ...,
        description=(
            "true only when the text states that this fact is a change in the documented version (a baseline, a "
            "removal, a rename, a replacement, a deprecation, a move, a changed default or something new); false "
            "when the fact only describes how something works, what it does or contains, or a limitation of "
            "another product"
        ),
    )


class CheckedExtractedEdges(BaseModel):
    edges: list[CheckedEdge]


def canonical_relation(relation: str, change_types: Collection[str] | None = None) -> str:
    """The closed change type a relation spells, or the relation unchanged."""
    closed = CHANGE_EDGE_TYPES if change_types is None else change_types
    spelled = "_".join(relation.replace("-", " ").split()).upper()
    return spelled if spelled in closed else relation


def check_change_edges(
    answer: dict[str, Any], change_types: Collection[str] | None = None
) -> tuple[dict[str, Any], int]:
    """Graphiti's answer from a self-checked one, and how many facts lost a change type.

    ``change_types`` is the episode profile's closed set; the change-record profile's by default.
    """
    closed = CHANGE_EDGE_TYPES if change_types is None else change_types
    edges: list[dict[str, Any]] = []
    demoted = 0
    for item in answer.get("edges") or ():
        edge = {key: value for key, value in item.items() if key != SELF_CHECK_FIELD}
        relation = canonical_relation(str(edge.get("relation_type") or ""), closed)
        if relation in closed and item.get(SELF_CHECK_FIELD) is not True:
            relation = NOT_A_CHANGE_RELATION
            demoted += 1
        edge["relation_type"] = relation
        edges.append(edge)
    return {"edges": edges}, demoted


__all__ = [
    "EDGE_PROMPT",
    "GRAPHITI_EDGE_ANSWER",
    "CheckedExtractedEdges",
    "canonical_relation",
    "check_change_edges",
]
