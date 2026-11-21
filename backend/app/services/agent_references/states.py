"""The closed reference states of workflow references.

One entry per workflow carries the *most significant* version that references the
agent, in this precedence:

* ``published`` - the version that runs: a workflow's current published version
  (``flow_definitions.current_version_id`` on a published flow);
* ``current_draft`` - the version the editor works on and that has not been
  published: a workflow's newest version when it is a draft;
* ``older_revision_only`` - only versions that neither run nor are edited reference
  the agent (superseded, unpublished or retired versions).

The editor opens the *latest* version, so every entry also carries
``latest_revision`` and ``latest_references_agent``: a client must never imply that
the editor link shows a referencing revision the latest revision no longer contains.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

PUBLISHED = "published"
CURRENT_DRAFT = "current_draft"
OLDER_REVISION_ONLY = "older_revision_only"

REFERENCE_STATES: tuple[str, ...] = (PUBLISHED, CURRENT_DRAFT, OLDER_REVISION_ONLY)


def most_significant(candidates: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    """Pick ``(state, revision)`` by state precedence, then the highest revision number."""
    ranked = sorted(candidates, key=lambda item: (REFERENCE_STATES.index(item[0]), -item[1]))
    return ranked[0] if ranked else None


@dataclass(frozen=True, slots=True)
class Reference:
    """The most significant referencing revision and what the editor link opens."""

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
