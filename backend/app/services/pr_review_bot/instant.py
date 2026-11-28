"""The instant trigger: a pull request Octryx opened, or a commit Octryx pushed onto one, is reviewed at once (a harness
may merge or close its pull requests within minutes, before the hourly sync sees them)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.workflow_run import WorkflowRunEvent
from ...time_utils import utc_now
from .starter import TRIGGER_OCTRYX, WORKFLOW_KEY

logger = logging.getLogger(__name__)

EVENT_KIND = "pr_head_ready"
TICK_SECONDS = 5
#: After a restart, the events of this window are read again (the start answers ``already_reviewed`` for the done).
CATCH_UP = timedelta(minutes=15)
#: A listing that fails (or does not show the head yet) is tried again on the next ticks, this many times.
ATTEMPTS = 3


def head_ready(db: AsyncSession, run: WorkflowRun) -> None:
    pr = dict(run.pull_request or {})
    if run.workflow_key == WORKFLOW_KEY or not pr.get("id") or pr.get("state", "open") != "open":
        return
    from ..workflow_runs.records import record_event

    record_event(db, run, EVENT_KIND, node_id=run.current_node_id, detail={
        "pr_id": str(pr["id"]), "head_sha": str(dict(run.context or {}).get("head_sha") or "")})


@dataclass
class Cursor:
    since: datetime = field(default_factory=lambda: utc_now() - CATCH_UP)
    seen: set[str] = field(default_factory=set)
    tries: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Due:
    event_id: str
    created_at: datetime
    project_id: str
    repository: str
    pr_id: str


async def _due(db: AsyncSession, cursor: Cursor) -> list[_Due]:
    rows = (await db.execute(
        select(WorkflowRunEvent.id, WorkflowRunEvent.created_at, WorkflowRunEvent.detail, WorkflowRun.project_id,
               WorkflowRun.repository).join(WorkflowRun, WorkflowRun.id == WorkflowRunEvent.run_id)
        .where(WorkflowRunEvent.kind == EVENT_KIND, WorkflowRunEvent.created_at >= cursor.since)
        .order_by(WorkflowRunEvent.created_at).limit(200))).all()
    return [_Due(str(event_id), created_at, str(project_id), str(repository or ""),
                 str(dict(detail or {}).get("pr_id") or ""))
            for event_id, created_at, detail, project_id, repository in rows if str(event_id) not in cursor.seen]


async def _start_one(db: AsyncSession, item: _Due) -> str:
    from ..observability.review_bot_metrics import count_trigger
    from .bot_user import ensure_review_bot_user
    from .comment_poll import list_repository
    from .settings import repository_record, settings_of
    from .starter import start_review
    from .sync import head_event

    record = await repository_record(db, item.project_id, item.repository)
    if record is None or not (settings_of(record).on_sync() or settings_of(record).on_webhook()):
        return "skipped"  # the bot is off for the repository: nothing to list
    bot = await ensure_review_bot_user(db, str(record.project_id))
    await db.commit()
    answer = await list_repository(db, record, bot.id)
    listed = [pr for pr in answer["pull_requests"] if isinstance(pr, dict) and str(pr.get("number")) == item.pr_id]
    event = head_event(item.repository, listed[0]) if listed else None
    if event is None:
        return "not_open"  # merged or closed before the review could start
    outcome = await start_review(db, str(record.project_id), event, trigger=TRIGGER_OCTRYX)
    count_trigger(TRIGGER_OCTRYX, event.provider, outcome.outcome, outcome.reason)
    return outcome.outcome


async def start_due(db: AsyncSession, cursor: Cursor) -> dict[str, int]:
    counted: dict[str, int] = {}
    due = await _due(db, cursor)
    newest = {(item.repository, item.pr_id): item for item in due}
    for (repository, pr_id), item in newest.items():
        try:
            outcome = await _start_one(db, item) if pr_id else "skipped"
        except Exception:  # noqa: BLE001 - logged; the event is tried again on the next ticks
            await db.rollback()
            logger.warning("pr_review_bot.instant_failed repository=%s pr=%s", repository, pr_id, exc_info=True)
            outcome = ""
        cursor.tries[item.event_id] = cursor.tries.get(item.event_id, 0) + 1
        if outcome or cursor.tries[item.event_id] >= ATTEMPTS:
            counted[outcome or "failed"] = counted.get(outcome or "failed", 0) + 1
            # The older events of the same pull request are answered by this start too.
            cursor.seen.update(other.event_id for other in due
                               if (other.repository, other.pr_id) == (repository, pr_id))
            cursor.tries.pop(item.event_id, None)
    if due and not cursor.tries:
        # Every event so far is answered: the cursor moves to the newest (the same instant is read again, ``seen``).
        cursor.since = max(item.created_at for item in due)
        cursor.seen = {item.event_id for item in due if item.created_at >= cursor.since}
    return counted


__all__ = ["ATTEMPTS", "EVENT_KIND", "TICK_SECONDS", "Cursor", "head_ready", "start_due"]
