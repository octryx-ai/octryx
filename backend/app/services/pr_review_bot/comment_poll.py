"""Where ``@octryx`` comments come from: the sync's poll and a webhook, both into ``commands``."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from . import bot_state
from .commands import Reply, handle_comment, parse_command
from .comment_events import CommentEvent, listed_comment
from .events import PullRequestEvent
from .providers import POST_TOOLS, pr_key
from .settings import repository_of, settings_of

logger = logging.getLogger(__name__)
OVERLAP = timedelta(minutes=5)
POLL_INTERVAL_SECONDS = 120


def _now() -> datetime:
    return datetime.now(UTC)


async def list_repository(db: AsyncSession, record: CodeRepository, user_id: str, **extra: Any) -> dict[str, Any]:
    from ...tools.registry import execute_tool_with_plugins
    from ..workflow_runs.platform.repo_ref import parse_repository
    from .providers import LIST_TOOLS
    from .sync import tool_context

    ref = parse_repository(repository_of(record))
    context = await tool_context(db, str(record.project_id), user_id)
    answer = await execute_tool_with_plugins(LIST_TOOLS[ref.provider], {**ref.args(), **extra}, context)
    if not isinstance(answer, dict) or answer.get("error") or not isinstance(answer.get("pull_requests"), list):
        raise RuntimeError(str((answer or {}).get("error") if isinstance(answer, dict) else answer)[:300])
    return answer


def _heads(repository: str, answer: dict[str, Any]) -> dict[str, PullRequestEvent]:
    from .sync import head_event

    events = [head_event(repository, pr) for pr in answer.get("pull_requests") or [] if isinstance(pr, dict)]
    return {event.pr_id: event for event in events if event is not None}


def _reply(db: AsyncSession, record: CodeRepository, user_id: str,
           heads: dict[str, PullRequestEvent]) -> tuple[Reply, dict[str, CommentEvent]]:
    current: dict[str, CommentEvent] = {}

    async def send(arguments: dict[str, Any], *, commit: str = "", event: CommentEvent | None = None) -> Any:
        from ...tools.registry import execute_tool_with_plugins
        from ..workflow_runs.platform.repo_ref import parse_repository
        from .sync import tool_context

        event = event or current.get("event")
        pr = heads.get(event.pr_id) if event is not None else None
        ref = parse_repository(event.repository) if event is not None else None
        if pr is None or ref is None or ref.provider not in POST_TOOLS:
            return None
        context = await tool_context(db, str(record.project_id), user_id, capability="deliver")
        return await execute_tool_with_plugins(POST_TOOLS[ref.provider], {
            **ref.args(), pr_key(ref.provider): event.pr_id, "commit": commit or pr.head_sha, **arguments}, context)

    async def post(text: str, event: CommentEvent) -> Any:
        current["event"] = event
        return await send({"thread_answers": [{"comment_id": event.thread_root, "reply": text, "resolve": False}]}
                          if event.inline else {"comment": text}, event=event)

    async def bound(arguments: dict[str, Any], *, commit: str = "") -> Any:
        return await send(arguments, commit=commit)

    return Reply(post, bound), current


def reply_for(db: AsyncSession, record: CodeRepository, user_id: str, heads: dict[str, PullRequestEvent],
              event: CommentEvent) -> Reply:
    reply, current = _reply(db, record, user_id, heads)
    current["event"] = event
    return reply


def _permission(db: AsyncSession, record: CodeRepository, user_id: str) -> Any:
    known: dict[str, str] = {}

    async def level(login: str) -> str:
        if login not in known:
            try:
                answer = await list_repository(db, record, user_id, permissions_for=[login])
                known[login] = str(dict(answer.get("permissions") or {}).get(login) or "unknown")
            except Exception:  # noqa: BLE001 - not readable: the Octryx role decides (``commands.authorized``)
                known[login] = "unknown"
        return known[login]

    return level


async def act_on(db: AsyncSession, record: CodeRepository, user_id: str, comments: list[CommentEvent],
                 heads: dict[str, PullRequestEvent]) -> dict[str, int]:
    counted: dict[str, int] = {}
    permission, (reply, current) = _permission(db, record, user_id), _reply(db, record, user_id, heads)
    for event in comments:
        current["event"] = event
        outcome = await handle_comment(db, str(record.project_id), record, event, heads.get(event.pr_id),
                                       permission=permission, reply=reply)
        counted[outcome] = counted.get(outcome, 0) + 1
    return counted


async def poll_comments(db: AsyncSession, record: CodeRepository, user_id: str,
                        answer: dict[str, Any] | None = None) -> dict[str, int]:
    started, since = _now(), bot_state.cursor(record)
    if not since:
        bot_state.set_cursor(record, started.isoformat())
        await db.commit()
        return {}
    if answer is None or "comments" not in answer:
        moment = datetime.fromisoformat(since) - OVERLAP
        answer = await list_repository(db, record, user_id, comments_since=moment.isoformat())
    repository = repository_of(record)
    listed = [event for item in answer.get("comments") or [] if isinstance(item, dict)
              and (event := listed_comment(repository, item)) is not None]
    heads = _heads(repository, answer)
    # A command counts in a comment on an open pull request only (a closed one's, or a review's summary, is read
    # for the corrections and nothing else); every other comment is a person's correction.
    comments = [event for event in listed if parse_command(event.body) and event.pr_id in heads
                and not event.comment_id.startswith("review-")]
    await _people_comments(db, str(record.project_id), [event for event in listed if event not in comments])
    counted = await act_on(db, record, user_id, comments, heads) if comments else {}
    bot_state.set_cursor(record, started.isoformat())
    await db.commit()
    return counted


def poll_since(record: CodeRepository) -> dict[str, str]:
    since = bot_state.cursor(record)
    return {"comments_since": (datetime.fromisoformat(since) - OVERLAP).isoformat()} if since else {}


async def poll_all(db: AsyncSession) -> dict[str, int]:
    from sqlalchemy import select

    from .bot_user import ensure_review_bot_user

    records = (await db.execute(select(CodeRepository).where(
        CodeRepository.is_active.is_(True), CodeRepository.project_id.is_not(None)))).scalars().all()
    totals: dict[str, int] = {}
    for record in [row for row in records if settings_of(row).on_sync() and repository_of(row)]:
        try:
            bot = await ensure_review_bot_user(db, str(record.project_id))
            for outcome, count in (await poll_comments(db, record, bot.id)).items():
                totals[outcome] = totals.get(outcome, 0) + count
        except Exception:  # noqa: BLE001 - logged; the next poll reads from the same cursor
            await db.rollback()
            logger.warning("pr_review_bot.poll_failed repository_id=%s", record.id, exc_info=True)
    return totals


async def _people_comments(db: AsyncSession, project_id: str, events: list[CommentEvent]) -> None:
    from ..workflow_runs.corrections import pr_comment
    from .finding_replies import remember

    for event in events:
        await pr_comment(db, project_id, event)
        await remember(db, project_id, event)


async def on_person_comment(project_id: str, event: CommentEvent, session_factory: Any = None) -> None:
    if session_factory is None:
        from ...db import async_session_factory as session_factory
    try:
        async with session_factory() as db:
            await _people_comments(db, project_id, [event])
            await db.commit()
    except Exception:  # noqa: BLE001 - information only; the poll of a syncing repository sees it again
        logger.warning("pr_review_bot.person_comment_failed repository=%s", event.repository, exc_info=True)


async def on_comment(project_id: str, event: CommentEvent, session_factory: Any = None) -> str:
    from .bot_user import ensure_review_bot_user
    from .settings import repository_record

    if session_factory is None:
        from ...db import async_session_factory as session_factory
    try:
        async with session_factory() as db:
            record = await repository_record(db, project_id, event.repository)
            settings = settings_of(record) if record is not None else None
            if record is None or not (settings.on_webhook() or settings.on_sync()):
                return "bot_off"
            bot = await ensure_review_bot_user(db, project_id)
            heads = _heads(repository_of(record), await list_repository(db, record, bot.id))
            return (await act_on(db, record, bot.id, [event], heads)).popitem()[0]
    except Exception:  # noqa: BLE001 - logged; a poll of a syncing repository acts on it instead
        logger.warning("pr_review_bot.command_failed repository=%s pr=%s", event.repository, event.pr_id,
                       exc_info=True)
        return "failed"


__all__ = ["OVERLAP", "POLL_INTERVAL_SECONDS", "act_on", "reply_for", "list_repository", "on_comment",
           "on_person_comment", "poll_all",
           "poll_comments", "poll_since"]
