"""The hourly pull request sync of the review bot (webhook and sync, per repository)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from ..observability.review_bot_metrics import count_trigger
from .bot_user import ensure_review_bot_user
from .events import PullRequestEvent
from .settings import repository_of, settings_of
from .starter import TRIGGER_SYNC, start_review

logger = logging.getLogger(__name__)


async def tool_context(db: AsyncSession, project_id: str, user_id: str, *, capability: str = "read_only") -> Any:
    from ...tools.context import ToolContext
    from ..project.service import get_project_config
    from ..run_capability.declared import SOURCE_FLOW_DEFINITION, declared_run_capability

    declared = declared_run_capability(capability, source=SOURCE_FLOW_DEFINITION)
    return ToolContext(user_id=user_id, project_ids=[project_id], roles=[], session_id=None,
                       project_config=await get_project_config(project_id, db), db=db,
                       run_capability=declared.tool_context_state(), workspace_root=None,
                       workflow_platform_action=True)


def head_event(repository: str, pr: dict[str, Any]) -> PullRequestEvent | None:
    number, sha, source = str(pr.get("number") or ""), str(pr.get("head_sha") or ""), str(pr.get("source_branch") or "")
    if not number or not source:
        return None
    path = repository.partition(":")[2].lower()
    head_repository = str(pr.get("head_repository") or "").strip().lower()
    return PullRequestEvent(repository, number, sha, source, str(pr.get("target_branch") or ""),
                            title=str(pr.get("title") or ""), author=str(pr.get("author") or ""),
                            url=str(pr.get("url") or ""), draft=bool(pr.get("draft")),
                            author_id=str(pr.get("author_id") or ""),
                            fork=bool(head_repository) and head_repository != path)


async def sync_repository(db: AsyncSession, record: CodeRepository, *, start: Any = None,
                          reasons: dict[str, int] | None = None) -> dict[str, int]:
    repository = repository_of(record)
    counted: dict[str, int] = {}
    if not repository or not settings_of(record).on_sync():
        return counted
    from .comment_poll import list_repository, poll_comments, poll_since

    bot = await ensure_review_bot_user(db, str(record.project_id))
    await db.commit()
    answer = await list_repository(db, record, bot.id, **poll_since(record))
    # The ``@octryx`` commands of the same listing first: a ``resume`` or ``review full`` holds for the
    # heads below in this pass (a resumed pull request does not wait for the next sync).
    commands = await poll_comments(db, record, bot.id, answer)
    for pr in [item for item in answer["pull_requests"] if isinstance(item, dict)]:
        event = head_event(repository, pr)
        if event is None:
            continue
        outcome = await start_review(db, str(record.project_id), event, trigger=TRIGGER_SYNC, start=start)
        count_trigger(TRIGGER_SYNC, event.provider, outcome.outcome, outcome.reason)
        counted[outcome.outcome] = counted.get(outcome.outcome, 0) + 1
        if reasons is not None and outcome.reason:
            reasons[outcome.reason] = reasons.get(outcome.reason, 0) + 1
    # Pull requests that left the open list with open findings (F3, counted once each).
    from .outcomes import count_closed

    open_numbers = {str(pr.get("number")) for pr in answer["pull_requests"] if isinstance(pr, dict)}
    if await count_closed(db, str(record.project_id), repository, open_numbers):
        await db.commit()
    for outcome, count in commands.items():
        counted[f"command_{outcome}"] = counted.get(f"command_{outcome}", 0) + count
    return counted


async def sync_all(db: AsyncSession) -> dict[str, int]:
    records = (await db.execute(select(CodeRepository).where(
        CodeRepository.is_active.is_(True), CodeRepository.project_id.is_not(None)))).scalars().all()
    totals: dict[str, int] = {}
    for record in [row for row in records if settings_of(row).on_sync()]:
        try:
            for outcome, count in (await sync_repository(db, record)).items():
                totals[outcome] = totals.get(outcome, 0) + count
        except Exception:  # noqa: BLE001 - one repository's failure is logged; the others still sync
            await db.rollback()
            logger.warning("pr_review_bot.sync_failed repository_id=%s", record.id, exc_info=True)
            totals["failed"] = totals.get("failed", 0) + 1
    return totals


__all__ = ["head_event", "sync_all", "sync_repository", "tool_context"]
