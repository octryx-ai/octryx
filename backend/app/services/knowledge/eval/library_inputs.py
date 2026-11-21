"""Shared vocabulary of the Library evaluation inputs: schemas, budget ceilings, value types."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "octryx.library_eval.manifest/v1"
PRIOR_QUERIES_SCHEMA = "octryx.library_eval.prior_queries/v1"
INVENTORY_SCHEMA = "octryx.library_eval.evidence_inventory/v1"

SPLITS = ("exploration", "regression", "calibration", "holdout")
KINDS = ("answer", "no_answer", "exclusion")
MODES = ("hybrid", "lexical", "vector")
# The search route fuses bound Workspaces only in hybrid mode; lexical and vector read the own Workspace.
MODE_SCOPE = {"hybrid": "library_scope", "lexical": "single_workspace", "vector": "single_workspace"}

# Hard ceilings of the root freeze; a manifest budget may only be lower.
MAX_SEARCH_REQUESTS = 8
MAX_RESULT_LIMIT = 10
MAX_SOURCE_READS = 0
MAX_TIMEOUT_S = 120
MAX_LOGICAL_PROVIDER_OPS = 96
# Conservative logical-operation estimate per search request (not a billing ceiling: provider retries
# may add attempts). Hybrid assumes the worst-case scope of the own Workspace plus five bindings, each
# with one query embedding and one rerank call.
WORST_CASE_SCOPE_WORKSPACES = 6
LOGICAL_PROVIDER_OPS = {"hybrid": 2 * WORST_CASE_SCOPE_WORKSPACES, "vector": 1, "lexical": 0}

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EvaluationInputError(ValueError):
    """A frozen input is invalid; ``problems`` lists every reason, nothing is scored."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def canonical_sha256(document: Any) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: str | Path) -> Any:
    def refuse_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value} in {path}")

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=refuse_constant)


def is_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


def is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_timestamp(value: Any) -> datetime | None:
    """An ISO-8601 timestamp with an explicit offset, else ``None``."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" \t.,;:!?\"'")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One evidence alternative: an exact key, or a span of an exact revision content."""

    evidence_key: str | None = None
    source_id: str | None = None
    content_sha256: str | None = None
    span_ordinal: int | None = None

    def matches(self, hit: dict[str, Any]) -> bool:
        if self.evidence_key is not None:
            return hit.get("evidence_key") == self.evidence_key
        return (
            hit.get("source_id") == self.source_id
            and hit.get("content_sha256") == self.content_sha256
            and hit.get("span_ordinal") == self.span_ordinal
        )

    def label(self) -> str:
        if self.evidence_key is not None:
            return f"key:{self.evidence_key}"
        return f"span:{self.source_id}:{self.content_sha256}:{self.span_ordinal}"


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    required: bool
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class Exclusion:
    kind: str  # "evidence_key" | "source_id" | "workspace_id"
    value: str


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    split: str
    kind: str
    workspace: str
    mode: str
    query: str
    limit: int
    products: tuple[str, ...] | None
    version: str | None
    facts: tuple[Fact, ...]
    exclusions: tuple[Exclusion, ...]

    @property
    def scope(self) -> str:
        return MODE_SCOPE[self.mode]


@dataclass(frozen=True, slots=True)
class Manifest:
    raw: dict[str, Any]
    sha256: str
    frozen_at: datetime
    workspaces: dict[str, str]  # alias -> project id
    workspace_names: dict[str, str]  # project id -> display name (root-provided, unique)
    budget: dict[str, int]
    cases: tuple[Case, ...]
    overlap_check: dict[str, Any] = field(default_factory=dict)

    @property
    def logical_provider_estimate(self) -> int:
        return sum(LOGICAL_PROVIDER_OPS[case.mode] for case in self.cases)
