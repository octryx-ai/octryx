"""The root-provided evidence inventory: which labelled spans exist, with provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .library_inputs import (
    INVENTORY_SCHEMA,
    EvaluationInputError,
    EvidenceRef,
    canonical_sha256,
    is_identifier,
    parse_timestamp,
)


@dataclass(frozen=True, slots=True)
class EvidenceInventory:
    """Root-provided, immutable record of which spans exist; matching is by key or by revision span."""

    sha256: str
    by_key: dict[str, dict[str, Any]]
    by_span: dict[tuple[str, str, int], dict[str, Any]]
    revisions_by_source: dict[str, set[str]]

    def verify(self, ref: EvidenceRef) -> str:
        """``verified``, ``stale`` (the source has other content) or ``missing``."""
        if ref.evidence_key is not None:
            return "verified" if ref.evidence_key in self.by_key else "missing"
        if (ref.source_id, ref.content_sha256, ref.span_ordinal) in self.by_span:
            return "verified"
        return "stale" if ref.source_id in self.revisions_by_source else "missing"


def load_inventory(document: Any) -> EvidenceInventory:
    problems: list[str] = []
    if not isinstance(document, dict) or document.get("schema") != INVENTORY_SCHEMA:
        raise EvaluationInputError([f"inventory: schema must be {INVENTORY_SCHEMA}"])
    by_key: dict[str, dict[str, Any]] = {}
    by_span: dict[tuple[str, str, int], dict[str, Any]] = {}
    revisions: dict[str, set[str]] = {}
    spans = document.get("spans")
    if not isinstance(spans, list):
        raise EvaluationInputError(["inventory: spans must be a list"])
    for index, entry in enumerate(spans):
        ok = (
            isinstance(entry, dict)
            and is_identifier(entry.get("source_id"))
            and is_identifier(entry.get("revision_id"))
            and isinstance(entry.get("content_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", entry["content_sha256"]) is not None
            and all(type(entry.get(key)) is int for key in ("span_ordinal", "span_count"))
            # One-based like KnowledgeEvidenceSpan: the last span of a revision has ordinal == count.
            and 1 <= entry["span_ordinal"] <= entry["span_count"]
            and isinstance(entry.get("verified_by"), str)
            and entry["verified_by"].strip()
            and parse_timestamp(entry.get("verified_at")) is not None
            and isinstance(entry.get("method"), str)
            and entry["method"].strip()
        )
        if not ok:
            problems.append(
                f"inventory span[{index}]: needs source, revision, hash, 1 <= ordinal <= count and provenance"
            )
            continue
        by_key[f"{entry['revision_id']}:{entry['span_ordinal']}"] = entry
        by_span[(entry["source_id"], entry["content_sha256"], entry["span_ordinal"])] = entry
        revisions.setdefault(entry["source_id"], set()).add(entry["content_sha256"])
    if problems:
        raise EvaluationInputError(problems)
    return EvidenceInventory(canonical_sha256(document), by_key, by_span, revisions)
