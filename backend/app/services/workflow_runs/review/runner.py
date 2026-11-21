"""The ``review`` node: the independent reviewer reviews the change, the server records its verdict.

Entering a ``review`` node makes the run wait (``awaiting_review``). :func:`run_due_reviews` (the review worker,
every few seconds) takes each waiting run, outside any request:

1. claims the run and marks the attempt (``waiting.attempt``), so one review runs per pass even with several
   workers; an attempt older than :data:`STALE_ATTEMPT_MINUTES` (a crashed worker) is taken over;
2. builds the task from server-read facts only (``evidence``) and asks the governed reviewer model (``model``) —
   no tool, no history: the built-in **Reviewer** agent is read-only by construction;
3. claims the run again and records the verdict only when the run still waits for that attempt: the verdict
   (``context.review``, with the attempt, the node pass and its time), a ``UsageEvent`` on the run's session and
   an event; the run then goes on to the next node — a gate with ``review_passed`` and the deterministic evidence
   checks decides, and its loop edge takes the findings back to the fix phase within *n*.

No verdict (the model unavailable, an answer that breaks the schema, or no change of this pass to review) never
passes and never consumes a loop iteration. The model unavailable or an answer that is no verdict is asked again by
itself (:data:`RETRY_WAIT_MINUTES`, about 10 minutes); after that, and at once for anything else, the run pauses
(``review_no_decision``) and continuing reruns the review.
The verdict records the reviewed tree; the platform pushes only that tree (``platform/scm.push``).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ..records import WorkflowRunError, lock_run, record_event
from ..states import EVENT_WAITING, PAUSE_REVIEW_NO_DECISION, STATUS_WAITING, WAITING_REVIEW
from .attempts import _claim_attempt, _due, _record_usage, _retryable, _waiting, kept_findings, shallow_review
from .model import governed_review_model
from .review_call import ModelFactory, _ask

logger = logging.getLogger(__name__)

EVENT_REVIEW = "review_verdict"


def enter_review(db: AsyncSession, run: WorkflowRun, node: Any) -> None:
    """The run waits for its independent review (the worker runs it)."""
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_REVIEW
    run.node_state = {**dict(run.node_state or {}), "waiting": {
        "kind": WAITING_REVIEW, "title": node.title, "since": utc_now().isoformat(),
        "question": "The independent reviewer reviews the change."}}
    record_event(db, run, EVENT_WAITING, node_id=node.id, detail={"waiting_kind": WAITING_REVIEW})


# A review without a verdict for a passing reason (the model unavailable, an answer that is no verdict) is asked again
# by itself after these waits (minutes), about 10 minutes in all, before the run pauses for a person. Without
# them, runs paused for a person on exactly these (model_unavailable,
# invalid_verdict), each solved by pressing continue.
RETRY_WAIT_MINUTES = (1, 3, 6)
EVENT_REVIEW_RETRY = "review_retry_scheduled"


async def review_one(db: AsyncSession, run_id: str, *, model_factory: ModelFactory = governed_review_model) -> bool:
    """Run the review of one waiting run; ``True`` when a verdict or a pause was recorded."""
    run = await db.get(WorkflowRun, run_id)
    if run is None or not _due(run, utc_now()):
        return False
    attempt = await _claim_attempt(db, run)
    if attempt is None:
        return False
    verdict, usage, reason, tree, facts = await _ask(db, run, model_factory)
    run = await db.get(WorkflowRun, run_id)
    try:
        run = await lock_run(db, run)
    except WorkflowRunError:
        return False
    if run.waiting_kind != WAITING_REVIEW or _waiting(run).get("attempt") != attempt:
        await db.rollback()
        return False  # the run moved on (aborted, or another attempt took over): this verdict counts for nothing
    snapshot = facts.pop("_snapshot", None)
    diff_lines = int(facts.pop("_diff_lines", 0) or 0)
    decisions = facts.pop("spec_decisions", None)  # its own event, not repeated on the review's
    record = facts.pop("_record", None) or (verdict.to_dict() if verdict is not None else {})
    if snapshot is not None:
        from .artefact_runner import still_current

        if not await still_current(db, run, snapshot):
            await db.rollback()
            return False
    await _record_usage(db, run, usage, attempt)
    node_id = run.current_node_id
    if verdict is None:
        return await _no_verdict(db, run, reason, attempt)
    await _record_verdict(db, run, verdict, usage, tree, facts, record=record, attempt=attempt, node_id=node_id,
                          snapshot=snapshot, diff_lines=diff_lines, decisions=decisions)
    return True


async def _no_verdict(db: AsyncSession, run: WorkflowRun, reason: str, attempt: str) -> bool:
    """No verdict: ask again later when the reason is retryable and retries are left, else pause for a person."""
    from ..limits import pause_run

    if _retryable(reason) and _schedule_retry(db, run, reason, attempt):
        await db.commit()
        return True
    pause_reason = "needs_configuration" if reason.startswith("needs_configuration:") else PAUSE_REVIEW_NO_DECISION
    await pause_run(db, run, reason=pause_reason,
                    actor_id=None, detail={
        "message": f"the independent review gave no verdict ({reason})", "resume": {"kind": "rerun"}})
    await db.commit()
    return True


async def _record_verdict(db: AsyncSession, run: WorkflowRun, verdict: Any, usage: Any, tree: str,
                          facts: dict[str, Any], *, record: dict[str, Any], attempt: str, node_id: str | None,
                          snapshot: Any, diff_lines: int, decisions: Any) -> None:
    """Record the verdict on the run with its events, then the run goes on to its next node."""
    from ..corrections import review_fixed
    from ..engine import resolve_current_node

    code_binding = {"has_change": True, "tree": tree} if snapshot is None else {}
    reviewed_before = str(dict(dict(run.context or {}).get("review") or {}).get("tree") or "")
    run.context = {**dict(run.context or {}), "review": {
        **record, "attempt": attempt, "node_id": node_id, **code_binding,
        "at": utc_now().isoformat(), **facts}}
    # The findings this round answered as fixed (From Correction to Check), with the trees before and after the fix.
    await review_fixed(db, run, record, before_tree=reviewed_before, after_tree=str(tree or ""))
    await _tasks_after_review(db, run)
    if shallow := await shallow_review(db, verdict, usage, diff_lines):
        # Luna wrote 6.6k output tokens for 14 reviews. A warning on the run, never a verdict.
        record_event(db, run, "review_shallow", node_id=node_id, detail=shallow)
    if decisions:
        record_event(db, run, "spec_decisions_checked", node_id=node_id, detail=decisions)
    record_event(db, run, EVENT_REVIEW, node_id=node_id, detail={
        "verdict": verdict.verdict, "attempt": attempt, "findings": len(verdict.findings), **facts,
        "finding_list": kept_findings(dict(run.context.get("review") or {}).get("findings"))})
    await resolve_current_node(db, run, None, actor_id=None)
    from ..auto_accept import auto_accept

    await auto_accept(db, run)  # the product owner answered at the start: a passed, verified story ships itself
    await db.commit()


async def _tasks_after_review(db: AsyncSession, run: WorkflowRun) -> None:
    """The run's task list after the verdict: a high finding sends a task back, otherwise done tasks are verified."""
    from .. import task_status
    from ..task_list import run_task_list

    if tasks := run_task_list(run):
        # Only a high finding sends a task back; with none open the done tasks are verified (medium and low ones
        # are notes for the product owner, ``auto_accept``). Otherwise one cosmetic medium per story kept
        # its tasks unverified, so no story could ship without the product owner.
        recorded = dict(run.context.get("review") or {})
        high = [item for item in recorded.get("findings") or [] if dict(item).get("severity") == "high"]
        moved = task_status.after_review(tasks, "changes" if high else "pass", high, run.id)
        if moved != tasks:
            await task_status.store(db, run, moved)


def _schedule_retry(db: AsyncSession, run: WorkflowRun, reason: str, attempt: str) -> bool:
    """Ask the reviewer again after the next wait of :data:`RETRY_WAIT_MINUTES`; ``False`` once they are used up
    (the run then pauses for a person). The run keeps waiting for its review meanwhile."""
    waiting = _waiting(run)
    done = int(waiting.get("retries") or 0)
    if done >= len(RETRY_WAIT_MINUTES):
        return False
    retry_at = utc_now() + timedelta(minutes=RETRY_WAIT_MINUTES[done])
    run.node_state = {**dict(run.node_state or {}), "waiting": {
        **{key: value for key, value in waiting.items() if key not in ("attempt", "started_at")},
        "retries": done + 1, "retry_at": retry_at.isoformat(), "last_no_decision": reason}}
    record_event(db, run, EVENT_REVIEW_RETRY, node_id=run.current_node_id, detail={
        "reason": reason, "retry": done + 1, "of": len(RETRY_WAIT_MINUTES), "at": retry_at.isoformat(),
        "attempt": attempt})
    return True


async def run_due_reviews(db: AsyncSession, *, model_factory: ModelFactory = governed_review_model) -> int:
    ids = list((await db.execute(select(WorkflowRun.id).where(
        WorkflowRun.status == STATUS_WAITING, WorkflowRun.waiting_kind == WAITING_REVIEW))).scalars().all())
    done = 0
    for run_id in ids:
        try:
            done += int(await review_one(db, run_id, model_factory=model_factory))
        except Exception:
            logger.exception("workflow_run.review_failed run_id=%s", run_id)
            await db.rollback()
    return done


class ReviewWorker:
    def __init__(self, session_factory, *, interval_seconds: int = 15) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task = None

    async def start(self) -> None:
        import asyncio

        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        import asyncio

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        import asyncio

        while True:
            try:
                async with self._session_factory() as db:
                    await run_due_reviews(db)
                async with self._session_factory() as db:
                    from ..hands_on.step import generate_due

                    await generate_due(db)  # the hands-on scenarios, written by the reviewer's model
                async with self._session_factory() as db:
                    from ...check_proposals.worker import draft_due

                    await draft_due(db)  # the checks proposed after a repeated correction
                async with self._session_factory() as db:
                    from ...check_proposals.proof import prove_due

                    await prove_due(db)  # their proof on a device, red on the past mistakes, green after the fix
            except Exception:
                logger.exception("Workflow run review worker failed")
            await asyncio.sleep(self._interval_seconds)


__all__ = [
    "EVENT_REVIEW",
    "ReviewWorker",
    "enter_review",
    "review_one",
    "run_due_reviews",
]
