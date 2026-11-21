"""The closed ``answer_evidence`` trace record of the answer evidence guard (imports nothing).

The record sits under :data:`ANSWER_EVIDENCE_KEY` in a turn trace's context snapshot. It holds the
guard decision and bounded counts only, never answer text or URLs:

- ``evidence_guard``: ``passed`` | ``marked`` | ``unsourced`` (see ``check``); ``reminded`` | ``refused`` stay
  readable on traces recorded before the proportionate guard;
- ``cited_count`` / ``uncited_count``: the answer's statement blocks with and without a source link;
- ``invented_url_count``: answer links that did not come from this turn's tool results;
- ``evidence_url_count``: the openable sources the turn's tool results carried;
- ``reminder_count``: evidence reminders the turn has sent so far (at most one).

``unsourced`` is the closed marker the UI renders for an answer that no source of this turn backs.
"""

from __future__ import annotations

from typing import Any

ANSWER_EVIDENCE_KEY = "answer_evidence"
GUARD_PASSED = "passed"
GUARD_REMINDED = "reminded"
GUARD_REFUSED = "refused"
GUARD_UNSOURCED = "unsourced"
# Delivered with its uncited claims or invented links marked (proportionate guard).
GUARD_MARKED = "marked"
GUARD_STATES = frozenset({GUARD_PASSED, GUARD_REMINDED, GUARD_REFUSED, GUARD_UNSOURCED, GUARD_MARKED})
COUNT_FIELDS = ("cited_count", "uncited_count", "invented_url_count", "evidence_url_count", "reminder_count")
_MAX_COUNT = 10_000


def read_answer_evidence(context_snapshot: object) -> dict[str, Any] | None:
    """The validated record of a trace's context snapshot, or ``None`` (closed values only)."""
    record = context_snapshot.get(ANSWER_EVIDENCE_KEY) if isinstance(context_snapshot, dict) else None
    if not isinstance(record, dict) or record.get("evidence_guard") not in GUARD_STATES:
        return None
    read: dict[str, Any] = {"evidence_guard": record["evidence_guard"]}
    for name in COUNT_FIELDS:
        value = record.get(name)
        read[name] = value if type(value) is int and 0 <= value <= _MAX_COUNT else None
    return read


__all__ = [
    "ANSWER_EVIDENCE_KEY",
    "COUNT_FIELDS",
    "GUARD_MARKED",
    "GUARD_PASSED",
    "GUARD_REFUSED",
    "GUARD_REMINDED",
    "GUARD_STATES",
    "GUARD_UNSOURCED",
    "read_answer_evidence",
]
