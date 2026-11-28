"""A signed ``scm_pull_request`` webhook call reaches the review bot (concept §4: an event *starts* a run)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration.webhook import Webhook
from ..data_access import background_viewer, run_as
from ..data_access.read_filter import hidden_from_viewer
from ..observability.review_bot_metrics import count_trigger
from .events import PullRequestEvent, pull_request_event
from .starter import SKIPPED, TRIGGER_WEBHOOK, StartOutcome, admit, start_review

logger = logging.getLogger(__name__)
QUEUED = "queued"
_BACKGROUND: set[asyncio.Task] = set()  # held until done: a task without a reference may be collected mid-run
DEBOUNCE_SECONDS = 90.0
SUPERSEDED = "superseded"
# The newest head a webhook announced per (Workspace, repository, pull request), in this process. A start lost with a
# restart is picked up by the hourly sync.
_LATEST: dict[tuple[str, str, str], str] = {}


def _key(project_id: str, event: PullRequestEvent) -> tuple[str, str, str]:
    return project_id, event.repository, event.pr_id


async def _wait(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def start_in_background(project_id: str, event: PullRequestEvent, session_factory: Any = None) -> None:
    if session_factory is None:
        from ...db import async_session_factory as session_factory
    if DEBOUNCE_SECONDS > 0:
        await _wait(DEBOUNCE_SECONDS)
        if _LATEST.get(_key(project_id, event), event.head_sha) != event.head_sha:
            count_trigger(TRIGGER_WEBHOOK, event.provider, SUPERSEDED, "newer_push")
            return
    _LATEST.pop(_key(project_id, event), None)
    try:
        async with session_factory() as db:
            if project_id in await hidden_from_viewer(db):
                outcome = StartOutcome(SKIPPED, "workspace_not_visible")
            else:
                outcome = await start_review(db, project_id, event, trigger=TRIGGER_WEBHOOK)
    except Exception as error:  # noqa: BLE001 - logged and counted; the hourly sync reviews the head instead
        logger.warning("pr_review_bot.webhook_start_failed repository=%s pr=%s", event.repository, event.pr_id,
                       exc_info=True)
        outcome = StartOutcome("failed", type(error).__name__)
    count_trigger(TRIGGER_WEBHOOK, event.provider, outcome.outcome, outcome.reason)


def _spawn(coroutine: Any) -> None:
    # The webhook's verified principal, without the request's lifetime: the work runs after the answer.
    task = asyncio.create_task(run_as(background_viewer(), coroutine))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def on_scm_webhook(db: AsyncSession, webhook: Webhook, payload: Any, headers: Mapping[str, str], *,
                         is_test: bool) -> dict[str, str] | None:
    event = pull_request_event(payload, headers)
    if event is None and webhook.project_id and not is_test:
        return _on_comment(webhook.project_id, payload, headers)
    if event is None or not webhook.project_id:
        return None
    if is_test:
        return StartOutcome(SKIPPED, "test_call").to_dict()
    try:
        refused = await admit(db, webhook.project_id, event, trigger=TRIGGER_WEBHOOK)
    except Exception:  # noqa: BLE001 - the watching runs already got the event; the sync reviews the head
        logger.warning("pr_review_bot.webhook_admit_failed webhook_id=%s", webhook.id, exc_info=True)
        await db.rollback()
        refused = StartOutcome("failed", "admit_failed")
    if refused is not None:
        count_trigger(TRIGGER_WEBHOOK, event.provider, refused.outcome, refused.reason)
        return refused.to_dict()
    _LATEST[_key(webhook.project_id, event)] = event.head_sha
    _spawn(start_in_background(webhook.project_id, event))
    return {"outcome": QUEUED}


def _on_comment(project_id: str, payload: Any, headers: Mapping[str, str]) -> dict[str, str] | None:
    from .commands import parse_command
    from .comment_events import comment_event
    from .comment_poll import on_comment, on_person_comment

    comment = comment_event(payload, headers)
    if comment is None:
        return None
    if parse_command(comment.body) is None:
        _spawn(on_person_comment(project_id, comment))  # a person's correction, kept (From Correction to Check)
        return None
    _spawn(on_comment(project_id, comment))
    return {"outcome": QUEUED, "reason": "command"}


__all__ = ["DEBOUNCE_SECONDS", "QUEUED", "SUPERSEDED", "on_scm_webhook", "start_in_background"]
