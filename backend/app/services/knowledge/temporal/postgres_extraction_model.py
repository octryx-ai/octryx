"""The prompt, answer shape and name rules of the PostgreSQL graph extraction (``postgres_extraction``)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .change_self_check import canonical_relation
from .change_types import NOT_A_CHANGE_RELATION
from .extraction_profiles import ExtractionProfile

SPANS_PER_CALL = 8
MAX_FACTS_PER_CALL = 80
MAX_NAME_CHARS = 200
MAX_FACT_CHARS = 1000
MAX_PASSAGE_CHARS = 4000
SAME_ENTITY_SIMILARITY = 0.92
MAX_ANSWER_TOKENS = 8192
# An answer that is not the JSON object asked for is resampled once, as Graphiti did.
ANSWER_ATTEMPTS = 2
_RELATION = re.compile(r"[^A-Z0-9]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _Message:
    role: str
    content: str


class ExtractedFact(BaseModel):
    passage: int = Field(..., description="The number of the passage the fact is read from")
    source: str = Field(..., description="The entity the fact is about, as named in the passage")
    relation: str = Field(..., description="One relation type from the list, or a short UPPER_SNAKE_CASE verb phrase")
    target: str = Field(..., description="The other entity, as named in the passage")
    fact: str = Field(..., description="The fact as one short sentence, in the passage's language")
    states_version_change: bool = Field(
        False,
        description=(
            "true only when the passage states that this fact is a change in the documented version (a baseline, a "
            "removal, a rename, a replacement, a deprecation, a move, a changed default or something new); false "
            "when it only describes how something works"
        ),
    )


class ExtractionAnswer(BaseModel):
    facts: list[ExtractedFact]


@dataclass(frozen=True, slots=True)
class SpanInput:
    ordinal: int
    text: str


@dataclass(slots=True)
class BatchResult:
    spans: int = 0
    facts: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    edges_merged: int = 0
    demoted: int = 0
    dropped: int = 0


def normalized_name(name: str) -> str:
    return _SPACE.sub(" ", name).strip().strip(".,;:\"'`()[]").casefold()


def normalized_fact(fact: str) -> str:
    return _SPACE.sub(" ", fact).strip().casefold()


def episode_uuid(project_id: str, revision_id: str, ordinal: int, profile: str) -> str:
    """Stable per span and profile, so a rerun replaces the same episode."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"octryx-graph:{project_id}:{revision_id}:{ordinal}:{profile}"))


def build_messages(
    profile: ExtractionProfile, *, title: str, group: str, version: str | None, spans: list[SpanInput]
) -> list[_Message]:
    """The prompt: what to extract (the profile's types and instructions), then the numbered passages."""
    lines = [
        "You read numbered passages of one document and extract the facts they state.",
        f"Document: {title}" + (f" (product {group}, version {version})" if version else f" (product {group})"),
        "A fact links two named entities (a product, component, API, class, property, module, library, database,",
        "platform, standard or version) with one relation, stated as one short sentence. Extract only what a passage",
        "states; do not infer, do not add general knowledge, and skip passages without such a fact (tables of",
        "contents, legal text, empty headings).",
    ]
    if profile.edge_type_definitions:
        lines.append("Relation types (use the type that fits; otherwise a short UPPER_SNAKE_CASE verb phrase):")
        lines += [f"- {item.name}: {_SPACE.sub(' ', item.description)}" for item in profile.edge_type_definitions]
    else:
        lines.append("Relations are short UPPER_SNAKE_CASE verb phrases, for example USES, PART_OF, CONFIGURED_BY.")
    instructions = profile.instructions(group, version)
    if instructions:
        lines += ["Instructions:", instructions]
    lines += [
        "Answer with one JSON object and nothing else, of this shape:",
        '{"facts": [{"passage": 1, "source": "...", "relation": "...", "target": "...", "fact": "...",'
        ' "states_version_change": false}]}',
        f"At most {MAX_FACTS_PER_CALL} facts. An empty list is a valid answer.",
    ]
    passages = "\n\n".join(f"Passage {index}:\n{span.text[:MAX_PASSAGE_CHARS]}" for index, span in enumerate(spans, 1))
    return [_Message("system", "\n".join(lines)), _Message("user", passages)]


def _relation(raw: str, profile: ExtractionProfile, states_change: bool, result: BatchResult) -> str | None:
    closed = frozenset(item.name for item in profile.edge_type_definitions)
    relation = canonical_relation(raw, closed) if closed else raw
    if relation in closed and profile.self_check and not states_change:
        result.demoted += 1
        return NOT_A_CHANGE_RELATION
    if relation in closed:
        return relation
    spelled = _RELATION.sub("_", raw.upper()).strip("_")[:60]
    return spelled or None


def _vector(values: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"
