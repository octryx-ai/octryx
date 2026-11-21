"""Start the ``pr-review-bot`` run for a pull request head, once (concept §4, stage A).

Both triggers end here: a webhook event (``webhook.on_scm_webhook``) and the hourly sync (``sync``). Each decides by
the repository's opt-in (``settings``) and answers one closed outcome:

- ``started``: a run reviews this head (its id is returned);
- ``already_reviewed``: a run of the bot exists for this pull request and head commit, from either trigger (a
  webhook and the sync never review the same push twice; the sync also catches a missed webhook);
- ``skipped`` with a reason: ``not_registered`` (no Workspace repository), ``bot_off`` (the trigger is not switched
  on for the repository), ``draft`` (a draft, unless ``review_drafts``), ``fork`` (the source branch lives in a fork:
  checking it out needs a maintainer's approval, a later stage), ``no_head`` (the event names no commit).

The bot never reviews a pull request as the session that wrote it: the reviewer is the independent review node, a
fresh session without the author's history (``review.runner``). A run that opened the pull request is named in the
run's context (``authored_by_run``), so the summary says the run's own review was the first pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .bot_user import ensure_review_bot_user
from .events import PullRequestEvent
from .settings import repository_record, settings_of

logger = logging.getLogger(__name__)

WORKFLOW_KEY = "pr-review-bot"
CONTEXT_KEY = "pr_review"
STARTED, ALREADY_REVIEWED, SKIPPED = "started", "already_reviewed", "skipped"
TRIGGER_WEBHOOK, TRIGGER_SYNC, TRIGGER_COMMAND = "webhook", "sync", "command"
# A pull request Octryx opened or pushed onto (``instant``): reviewed at once when the bot is on with any trigger.
TRIGGER_OCTRYX = "octryx_pr"
# Runs of one repository looked at to find the same head (newest first): far more than one repository's open
# pull requests are pushed to between two syncs.
_RECENT_RUNS = 500


@dataclass(frozen=True, slots=True)
class StartOutcome:
    outcome: str
    reason: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in (("outcome", self.outcome), ("reason", self.reason),
                                              ("run_id", self.run_id)) if value}


def same_head(recorded: str, head: str) -> bool:
    """Bitbucket Cloud webhooks name the short hash (12 characters), its API and a checkout the full one."""
    recorded, head = recorded.lower(), head.lower()
    return bool(recorded and head) and (recorded.startswith(head) or head.startswith(recorded))


def _ended_without_review(run: WorkflowRun, facts: dict[str, Any]) -> bool:
    """A run that ended without posting a review (blocked: no checkout, nothing posted) does not count: the next
    sync or push tries the head again. Otherwise runs blocked on a refused checkout leave every later sync answering
    already_reviewed for heads nobody has reviewed."""
    return run.completed_at is not None and run.outcome != "done" and not facts.get("posted")


async def reviewed_run(db: AsyncSession, project_id: str, event: PullRequestEvent) -> WorkflowRun | None:
    """The run that reviewed (or is reviewing) this pull request head; a run that ended without a review is none."""
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == project_id, WorkflowRun.workflow_key == WORKFLOW_KEY,
        WorkflowRun.repository == event.repository,
    ).order_by(WorkflowRun.created_at.desc()).limit(_RECENT_RUNS))).scalars().all()
    for run in rows:
        facts = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
        if str(facts.get("pr_id")) == event.pr_id and not _ended_without_review(run, facts) and (
                same_head(str(facts.get("head_sha") or ""), event.head_sha)
                or same_head(str(facts.get("reviewed_sha") or ""), event.head_sha)):
            return run
    return None


async def _authoring_run(db: AsyncSession, project_id: str, event: PullRequestEvent) -> str:
    """The Octryx run that opened this pull request, if one did (its ``pull_request`` names the same id)."""
    rows = (await db.execute(select(WorkflowRun.id, WorkflowRun.pull_request).where(
        WorkflowRun.project_id == project_id, WorkflowRun.repository == event.repository,
        WorkflowRun.workflow_key != WORKFLOW_KEY, WorkflowRun.branch == event.source_branch,
    ))).all()
    return next((str(run_id) for run_id, pr in rows
                 if str(dict(pr or {}).get("id") or dict(pr or {}).get("number") or "") == event.pr_id), "")


def _skip_reason(event: PullRequestEvent, settings: Any, trigger: str) -> str:
    if trigger in (TRIGGER_COMMAND, TRIGGER_OCTRYX):
        if not (settings.on_webhook() or settings.on_sync()):
            return "bot_off"
    elif not (settings.on_webhook() if trigger == TRIGGER_WEBHOOK else settings.on_sync()):
        return "bot_off"
    if event.draft and not settings.review_drafts:
        return "draft"
    if event.fork:
        return "fork"
    return "no_head" if not event.head_sha else ""


async def admit(db: AsyncSession, project_id: str, event: PullRequestEvent, *, trigger: str,
                force_full: bool = False) -> StartOutcome | None:
    """Why ``event`` starts no run, or ``None`` when it does; reads only (a webhook answers with it at once).

    An ``@octryx review full`` (``force_full``, stage D) reviews a head again and also a paused pull request."""
    from .bot_state import is_paused

    record = await repository_record(db, project_id, event.repository)
    if record is None:
        return StartOutcome(SKIPPED, "not_registered")
    reason = _skip_reason(event, settings_of(record), trigger)
    if not reason and not force_full and is_paused(record, event.pr_id):
        reason = "paused"  # ``@octryx pause`` (stage D)
    if reason:
        return StartOutcome(SKIPPED, reason)
    if force_full:
        return None
    existing = await reviewed_run(db, project_id, event)
    return StartOutcome(ALREADY_REVIEWED, run_id=existing.id) if existing is not None else None


async def start_review(db: AsyncSession, project_id: str, event: PullRequestEvent, *, trigger: str,
                       start: Any = None, force_full: bool = False, requested_by: str = "") -> StartOutcome:
    """Start the bot's run for ``event`` when the repository opted in; commits on a start. The run's first steps
    (the checkout, the pending status) run within this call, as for every run start."""
    refused = await admit(db, project_id, event, trigger=trigger, force_full=force_full)
    if refused is not None:
        return refused
    from ..workflow_runs.records import new_chat_session
    from ..workflow_runs.states import CONTEXT_TRIGGER

    if start is None:
        from ..workflow_runs.records import start_run as start
    bot = await ensure_review_bot_user(db, project_id)
    facts = {**event.as_context(), "trigger": trigger,
             "authored_by_run": await _authoring_run(db, project_id, event),
             **({"force_full": True, "requested_by": requested_by} if force_full else {})}
    # The run's own chat session: its workspace (under the platform's data directory) is where the checkout lands.
    # Without a session the prepare tool falls back to the process's
    # working directory and the read-only code mount refuses it ("Permission denied: '/app/backend/var'").
    session = await new_chat_session(db, bot, project_id)
    run = await start(db, user=bot, workflow_key=WORKFLOW_KEY, project_id=project_id, repository=event.repository,
                      branch=event.source_branch, session=session,
                      context={CONTEXT_KEY: facts, CONTEXT_TRIGGER: trigger}, automatic=True)
    run.pull_request = {"id": event.pr_id, "url": event.url, "title": event.title}
    # The run's title is the pull request's: a review without a linked ticket shows it as the work it reviews
    # (otherwise the reviewer reads the workflow's name "PR review bot" as its work item).
    named = f"Pull request #{event.pr_id}" + (f": {event.title}" if event.title else "")
    run.title = named[:220]
    await db.commit()
    logger.info("pr_review_bot.started run_id=%s repository=%s pr=%s trigger=%s", run.id, event.repository,
                event.pr_id, trigger)
    return StartOutcome(STARTED, run_id=run.id)


__all__ = ["ALREADY_REVIEWED", "CONTEXT_KEY", "SKIPPED", "STARTED", "TRIGGER_OCTRYX", "TRIGGER_SYNC", "TRIGGER_WEBHOOK",
           "WORKFLOW_KEY",           "StartOutcome", "admit", "reviewed_run", "same_head", "start_review"]
