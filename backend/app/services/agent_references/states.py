"""The closed reference states of workflow references."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

PUBLISHED = "published"
CURRENT_DRAFT = "current_draft"
OLDER_REVISION_ONLY = "older_revision_only"

REFERENCE_STATES: tuple[str, ...] = (PUBLISHED, CURRENT_DRAFT, OLDER_REVISION_ONLY)


def most_significant(candidates: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    ranked = sorted(candidates, key=lambda item: (REFERENCE_STATES.index(item[0]), -item[1]))
    return ranked[0] if ranked else None


@dataclass(frozen=True, slots=True)
class Reference:
    state: str
    revision: int
    latest_revision: int
    latest_references_agent: bool


def reference_from(candidates: list[tuple[str, int]], latest_revision: int) -> Reference | None:
    best = most_significant(candidates)
    if best is None:
        return None
    in_latest = any(number == latest_revision for _, number in candidates)
    return Reference(best[0], best[1], latest_revision, in_latest)


__all__ = [
    "CURRENT_DRAFT",
    "OLDER_REVISION_ONLY",
    "PUBLISHED",
    "REFERENCE_STATES",
    "Reference",
    "most_significant",
    "reference_from",
]
