"""Line diff between two revisions of one source, over their plain text.

Both revisions are read through :func:`ledger.original.read_original`, so the diff has exactly the
original route's authorization: a revision of another source, of another Workspace, hidden by the
source ACL, or tombstoned is ``revision_not_found``. HTML originals are compared as the plain text
their display view extracts (``display/original_view.py``), so markup churn is not a change.

Bounded explicitly, never truncated: a side above the view's byte bound, :data:`MAX_DIFF_INPUT_CHARS` or
:data:`MAX_DIFF_INPUT_LINES` answers ``state: "too_large"`` with ``too_large_reason: "input"`` and
no diff; a unified diff longer than :data:`MAX_DIFF_OUTPUT_CHARS` answers ``"output"`` with its
stats but no diff text. ``difflib`` runs in a worker thread so a large comparison never stalls the
event loop.
"""

from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..ledger.original import OriginalContent, read_original
from ..ledger.original_errors import OriginalNotDisplayableError
from ..runtime import EvidenceRuntime
from .original_view import MAX_VIEW_BYTES, display_text, is_displayable, revision_origin

MAX_DIFF_INPUT_CHARS = 1_000_000
MAX_DIFF_INPUT_LINES = 10_000
MAX_DIFF_OUTPUT_CHARS = 500_000
CONTEXT_LINES = 3

STATE_OK = "ok"
STATE_IDENTICAL = "identical"
STATE_TOO_LARGE = "too_large"
REASON_INPUT = "input"
REASON_OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class LineDiff:
    unified: str
    added_lines: int
    removed_lines: int


def _within_input_bounds(text: str) -> bool:
    return len(text) <= MAX_DIFF_INPUT_CHARS and text.count("\n") < MAX_DIFF_INPUT_LINES


def line_diff(before: str, after: str, *, from_label: str, to_label: str) -> LineDiff:
    """Unified diff of two texts and its exact added/removed line counts."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            n=CONTEXT_LINES,
            lineterm="",
        )
    )
    added = removed = 0
    # The first two lines are the file headers; every later line is a hunk header or a prefixed line.
    for line in lines[2:]:
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return LineDiff(unified="\n".join(lines), added_lines=added, removed_lines=removed)


async def _side(
    db: AsyncSession, runtime: EvidenceRuntime, authorized: AuthorizedWorkspace, source_id: str, revision_id: str
) -> tuple[OriginalContent, dict]:
    original = await read_original(
        db, runtime=runtime, authorized=authorized, source_id=source_id, revision_id=revision_id
    )
    if not is_displayable(original.media_type):
        raise OriginalNotDisplayableError()
    origin = await revision_origin(db, authorized, revision_id)
    meta = {
        "revision_id": revision_id,
        "revision_ordinal": original.revision_ordinal,
        "content_type": original.media_type,
        "content_sha256": original.content_sha256,
        "source_changed_at": origin.source_changed_at,
    }
    return original, meta


async def diff_revisions(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    source_id: str,
    from_revision_id: str,
    to_revision_id: str,
) -> dict:
    """The bounded line diff ``from`` -> ``to`` of one source; refusals are the original route's."""
    before, from_meta = await _side(db, runtime, authorized, source_id, from_revision_id)
    after, to_meta = await _side(db, runtime, authorized, source_id, to_revision_id)
    payload: dict = {
        "workspace_id": authorized.project_id,
        "source_id": source_id,
        "from": from_meta,
        "to": to_meta,
        "limits": {
            "max_input_chars": MAX_DIFF_INPUT_CHARS,
            "max_input_lines": MAX_DIFF_INPUT_LINES,
            "max_diff_chars": MAX_DIFF_OUTPUT_CHARS,
        },
        "state": STATE_OK,
        "too_large_reason": None,
        "diff": None,
        "stats": None,
    }
    if before.content_sha256 == after.content_sha256:
        payload.update(state=STATE_IDENTICAL, stats={"added_lines": 0, "removed_lines": 0}, diff="")
        return payload
    if len(before.data) > MAX_VIEW_BYTES or len(after.data) > MAX_VIEW_BYTES:
        payload.update(state=STATE_TOO_LARGE, too_large_reason=REASON_INPUT)
        return payload
    before_text, after_text = display_text(before).text, display_text(after).text
    if not (_within_input_bounds(before_text) and _within_input_bounds(after_text)):
        payload.update(state=STATE_TOO_LARGE, too_large_reason=REASON_INPUT)
        return payload
    diff = await asyncio.to_thread(
        line_diff,
        before_text,
        after_text,
        from_label=f"r{from_meta['revision_ordinal']}",
        to_label=f"r{to_meta['revision_ordinal']}",
    )
    stats = {"added_lines": diff.added_lines, "removed_lines": diff.removed_lines}
    if len(diff.unified) > MAX_DIFF_OUTPUT_CHARS:
        payload.update(state=STATE_TOO_LARGE, too_large_reason=REASON_OUTPUT, stats=stats)
        return payload
    if not diff.unified:
        # Different bytes, same text (e.g. HTML markup only): no line changed.
        payload.update(state=STATE_IDENTICAL, stats=stats, diff="")
        return payload
    payload.update(diff=diff.unified, stats=stats)
    return payload


__all__ = [
    "MAX_DIFF_INPUT_CHARS",
    "MAX_DIFF_INPUT_LINES",
    "MAX_DIFF_OUTPUT_CHARS",
    "LineDiff",
    "diff_revisions",
    "line_diff",
]
