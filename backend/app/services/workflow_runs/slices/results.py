"""A slice's structured result and its merge.

- :func:`record_child_turn` — a child's turn ended (the turn-end checks report to the run as for any phase turn;
  a child's marker names its slice): its phase checks decide ``completed`` / ``failed``, the server commits the
  child's worktree, and the slice records a structured result — the commit, the files it changed, its newest test
  run (passed / failed tests), the checks it missed and a short summary. A report of an older child (a slice that
  was re-delegated meanwhile) changes nothing. The phase itself never advances on a child's turn.
- :func:`refresh_slices` — a child whose session ended without a report (timeout, crash) is ``failed`` with
  ``ended_without_result``: nothing stays ``running`` forever.
- :func:`merge_slices` — the main agent merges the completed slices into the run's working copy, one branch at a
  time; a conflict aborts that merge and marks the slice ``conflict`` with its files. The phase's gate
  (``slices_merged``) fails while any slice is not merged and its loop takes the findings back to the phase, where
  the main agent re-delegates (findings in the task, same worktree reset to the merged state).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ....time_utils import utc_now
from ..records import WorkflowRunError, lock_run, record_event
from . import worktrees
from .delegate import SLICE_METADATA_KEY, slice_view, slices_of

TERMINAL_SESSION = frozenset({"completed", "error", "failed", "cancelled", "timeout", "stopped"})
OPEN_STATUSES = frozenset({"running"})
MERGEABLE = frozenset({"completed"})


def slice_key_of(session: Session | None) -> str | None:
    marker = dict(getattr(session, "metadata_", None) or {}).get(SLICE_METADATA_KEY)
    return str(marker.get("key")) if isinstance(marker, dict) and marker.get("key") else None


def _tests(evidence: Any) -> dict[str, Any] | None:
    runs = list(getattr(evidence, "test_runs", None) or [])
    if not runs:
        return None
    last = runs[-1]
    results = dict(last.get("results") or {})
    return {"all_green": bool(last.get("all_green")),
            "passed": sorted(key for key, value in results.items() if value.get("outcome") == "passed")[:50],
            "failed": sorted(key for key, value in results.items() if value.get("outcome") in ("failed", "error"))[:50]}


async def record_child_turn(db: AsyncSession, run: WorkflowRun, *, key: str, session_id: str, state: str,
                            results: list[Any], evidence: Any) -> None:
    """The structured result of one child's turn (the caller holds the run claim)."""
    slices = slices_of(run)
    current = slices.get(key)
    if current is None or current.get("status") != "running" or current.get("child_session_id") != session_id:
        return  # a re-delegated or finished slice: an older child's report changes nothing
    path = Path(str(current.get("path") or ""))
    sha = await worktrees.commit_all(path, f"{run.ticket_key or run.workflow_key}: slice {key} "
                                           f"(iteration {current.get('iteration')})")
    missed = [str(getattr(item, "description", "") or getattr(item, "type", "")) for item in results
              if getattr(item, "blocking", False) and getattr(item, "outcome", "") == "failed"]
    current.update(
        status="completed" if state == "passed" else "failed",
        reason=None if state == "passed" else "checks_failed",
        result={"commit": sha or await worktrees.head(path), "files": await worktrees.changed_files(
                    path, str(current.get("base") or "HEAD")),
                "tests": _tests(evidence), "missed_checks": missed[:20],
                "summary": str(getattr(evidence, "answer", "") or "")[:800]},
        finished_at=utc_now().isoformat())
    slices[key] = current
    run.context = {**dict(run.context or {}), "slices": slices}
    record_event(db, run, "slice_finished", node_id=run.current_node_id,
                 detail={"slice": key, "status": current["status"], "iteration": current.get("iteration")})


async def refresh_slices(db: AsyncSession, run: WorkflowRun) -> bool:
    """Children that ended without reporting are ``failed`` (the caller holds the run claim)."""
    slices, changed = slices_of(run), False
    for key, item in slices.items():
        if item.get("status") not in OPEN_STATUSES:
            continue
        child = await db.get(Session, str(item.get("child_session_id") or ""))
        if child is None or str(child.status or "").lower() in TERMINAL_SESSION:
            item.update(status="failed", reason="ended_without_result", finished_at=utc_now().isoformat())
            slices[key], changed = item, True
    if changed:
        run.context = {**dict(run.context or {}), "slices": slices}
    return changed


async def merge_slices(db: AsyncSession, *, parent_session: Session) -> dict[str, Any]:
    """Merge every completed slice into the run's working copy; conflicts are reported, never half-merged."""
    from ..records import active_run_for_session

    run = await active_run_for_session(db, parent_session.id)
    if run is None or slice_key_of(parent_session):
        raise WorkflowRunError("not_a_run_phase", "Only the main agent of a workflow run phase merges slices.", 409)
    run = await lock_run(db, run)
    await refresh_slices(db, run)
    main = Path(str(dict(run.context or {}).get("local_path") or ""))
    slices = slices_of(run)
    await worktrees.commit_all(main, f"{run.ticket_key or 'workflow run'}: before merging slices")
    for key, item in sorted(slices.items()):
        if item.get("status") not in MERGEABLE:
            continue
        merged, conflicts = await worktrees.merge(main, str(item["branch"]),
                                                  f"{run.ticket_key or run.workflow_key}: merge slice {key}")
        if merged:
            item.update(status="merged", merged_sha=await worktrees.head(main), conflicts=None)
        else:
            item.update(status="conflict", conflicts=conflicts, reason="merge_conflict")
        slices[key] = item
        record_event(db, run, "slice_merge", node_id=run.current_node_id,
                     detail={"slice": key, "merged": merged, "conflicts": conflicts})
    base = str(dict(run.context or {}).get("base_sha") or "")
    if base and any(item.get("status") == "merged" for item in slices.values()):
        # The merged work lands uncommitted on the branch's base: the run pushes it as one commit; the slices'
        # own history stays on their branches.
        await worktrees.git(main, "reset", "--soft", base)
    run.context = {**dict(run.context or {}), "slices": slices}
    return {"status": "ok", "slices": [slice_view(item) for item in slices.values()]}


def slice_findings(run: WorkflowRun) -> list[str]:
    """One line per slice that is not merged: what the main agent re-delegates with."""
    lines = []
    for key, item in sorted(slices_of(run).items()):
        status = item.get("status")
        if status == "merged":
            continue
        result = dict(item.get("result") or {})
        detail = (f"conflicts in {', '.join(item.get('conflicts') or [])}" if status == "conflict"
                  else f"missed: {'; '.join(result.get('missed_checks') or [])}" if result.get("missed_checks")
                  else str(item.get("reason") or status))
        lines.append(f"slice {key} ({status}, iteration {item.get('iteration')}): {detail}")
    return lines


__all__ = ["merge_slices", "record_child_turn", "refresh_slices", "slice_findings", "slice_key_of"]
