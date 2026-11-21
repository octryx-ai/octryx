"""``@octryx`` commands in pull request comments.

A comment whose line starts with ``@octryx <command>`` reaches :func:`handle_comment` from a webhook
(``webhook``) or from the sync's poll (``sync``; a local installation gets no webhook). Each comment is acted on
once (``bot_state.first_time``) and always answered in the pull request:

- ``review full``: a full review of the current head, also of one reviewed before (no incremental pass);
- ``pause`` / ``resume``: no review starts for this pull request until it is resumed (webhook and sync);
- anything else: the list of commands.

Who may: a person whose linked account (Profile → Linked accounts) is the commenter, a member of the Workspace, with
write access to the repository (GitHub ``admin`` / ``maintain`` / ``write``). Where the platform does not tell
(Bitbucket: only a repository admin may read permissions), a Workspace admin or owner. Anybody else gets one answer
and nothing runs. The bot's own texts never start a line with ``@octryx``, so it never answers itself.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from ..observability.review_bot_metrics import count_trigger
from . import bot_state
from .comment_events import CommentEvent
from .events import PullRequestEvent
from .providers import PERMISSION_PROVIDERS, mention
from .starter import TRIGGER_COMMAND

logger = logging.getLogger(__name__)
REVIEW_FULL, PAUSE, RESUME, EXPLAIN, IGNORE, HELP = "review full", "pause", "resume", "explain", "ignore", "help"
FIX, WRITE_TESTS = "fix", "write tests"
_LINE = re.compile(r"^[ \t>]*@octryx\b[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
WRITE_LEVELS = frozenset({"admin", "maintain", "write"})
ADMIN_ROLES = frozenset({"admin", "owner"})
HELP_TEXT = ("Octryx understands: `review full` (a full review of the current head), `pause` (no reviews on this "
             "pull request), `resume`, `explain [question]` (in a finding's thread: why it matters and how to fix "
             "it), `ignore [reason]` (in a finding's thread: close it and propose a team rule), `fix [note]` (a fix "
             "run pushes a reviewed fix of the thread's finding, or of all open blocking findings) and `write tests "
             "[note]` (a run that only adds tests). Write it as the "
             "first word after the mention, for example `review full` after `@octryx`.")


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    args: str = ""


def parse_command(body: str) -> Command | None:
    """The first ``@octryx`` line of a comment; ``None`` when no line starts with the mention."""
    match = _LINE.search(body or "")
    if match is None:
        return None
    words = match.group(1).strip()
    lowered = words.lower()
    for name in (REVIEW_FULL, PAUSE, RESUME, EXPLAIN, IGNORE, WRITE_TESTS, FIX):
        if lowered == name or lowered.startswith(f"{name} "):
            return Command(name, words[len(name):].strip())
    return Command(HELP, words)


async def authorized(db: AsyncSession, project_id: str, event: CommentEvent,
                     permission: Callable[[str], Awaitable[str]]) -> tuple[str, str]:
    """``(Octryx user id, '')`` or ``('', why not)``."""
    from ..access_control import get_project_role_for_user
    from .seat_choice import linked_users

    roles = {}
    for user in await linked_users(db, event.repository, event.author, event.author_id):
        role = await get_project_role_for_user(db, user.id, project_id)
        if role is not None:
            roles[user.id] = role
    if not roles:
        return "", "only people with an Octryx account in this Workspace (a linked account for this login) can use it"
    level = await permission(event.author) if event.provider in PERMISSION_PROVIDERS else "unknown"
    if level in WRITE_LEVELS:
        return next(iter(roles)), ""
    admin = next((user_id for user_id, role in roles.items() if role in ADMIN_ROLES), "")
    if level == "unknown" and admin:
        return admin, ""
    if level == "unknown":
        return "", "write access could not be checked on this platform: a Workspace admin or owner can use it"
    return "", "only people with write access to this repository can use it"


@dataclass(slots=True)
class Reply:
    """How the answer reaches the pull request (``comment_poll``): ``post(text, event)`` in the command's thread or
    the conversation; ``send(arguments, commit=...)`` any other post-tool arguments for the pull request."""

    post: Callable[[str, CommentEvent], Awaitable[Any]]
    send: Callable[..., Awaitable[Any]] | None = None


async def handle_comment(db: AsyncSession, project_id: str, record: CodeRepository, event: CommentEvent,
                         pr: PullRequestEvent | None, *, permission: Callable[[str], Awaitable[str]],
                         reply: Reply) -> str:
    """Act on one comment; its outcome (``no_command``, ``seen``, ``refused``, ``closed`` or the command)."""
    command = parse_command(event.body)
    if command is None:
        return "no_command"
    if not bot_state.first_time(record, event.comment_id):
        return "seen"
    await db.commit()  # remembered before acting: a second poll or a webhook never acts on it again
    user_id, refused = await authorized(db, project_id, event, permission)
    if refused:
        await reply.post(f"Octryx: {refused}.", event)
        return _counted(event, "refused", command.name)
    if pr is None:
        await reply.post("Octryx: this pull request is not open any more.", event)
        return _counted(event, "closed", command.name)
    who = mention(event.provider, event.author)
    if command.name in (PAUSE, RESUME):
        bot_state.set_paused(record, event.pr_id, command.name == PAUSE)
        await db.commit()
        await reply.post("⏸️ Octryx paused its reviews on this pull request (by " + who + "). Resume them with "
                         "`resume` after the mention." if command.name == PAUSE else
                         f"▶️ Octryx resumed its reviews on this pull request (by {who}).", event)
    elif command.name == REVIEW_FULL:
        from .starter import start_review

        outcome = await start_review(db, project_id, pr, trigger=TRIGGER_COMMAND, force_full=True,
                                     requested_by=user_id)
        await reply.post(f"🔄 Octryx started a full review of `{pr.head_sha[:7]}` (requested by {who}, run "
                         f"`{outcome.run_id}`)." if outcome.run_id else
                         f"Octryx could not start a review: {outcome.reason or outcome.outcome}.", event)
    elif command.name == EXPLAIN:
        await _explain(db, project_id, pr, event, command.args)
    elif command.name == IGNORE:
        from .ignore import ignore_finding

        outcome = await ignore_finding(db, project_id, record, event, command.args, user_id, who, reply.send)
        return _counted(event, outcome, command.name)
    elif command.name in (FIX, WRITE_TESTS):
        from .fix_command import fix_command

        outcome = await fix_command(db, project_id, record, event, pr, user_id, command, reply)
        return _counted(event, outcome, command.name)
    else:
        await reply.post(HELP_TEXT, event)
    return _counted(event, "done", command.name)


async def _explain(db: AsyncSession, project_id: str, pr: PullRequestEvent, event: CommentEvent, question: str) -> None:
    """The explain run, in the background: its step asks the model and answers in the thread."""
    from .ignore import last_posted

    run = await last_posted(db, project_id, event.repository, event.pr_id)
    facts = dict(dict(run.context or {}).get("pr_review") or {}) if run is not None else {}
    known = [*(facts.get("open_findings") or []), *(facts.get("ignored") or [])]
    finding = next((dict(item) for item in known
                    if event.inline and str(item.get("comment_id") or "") == event.thread_root), None)
    spawn(_in_own_session(project_id, pr, event, question, finding))


async def _in_own_session(project_id: str, pr: PullRequestEvent, event: CommentEvent, question: str,
                          finding: dict[str, Any] | None) -> None:
    from ...db import async_session_factory
    from .explain import start_explain

    try:
        async with async_session_factory() as db:
            await start_explain(db, project_id, pr, event, question, finding)
    except Exception:  # noqa: BLE001 - logged; the person can ask again
        logger.warning("pr_review_bot.explain_failed repository=%s pr=%s", event.repository, event.pr_id,
                       exc_info=True)


def spawn(coroutine: Any) -> None:
    from .webhook import _spawn

    _spawn(coroutine)


def _counted(event: CommentEvent, outcome: str, name: str) -> str:
    count_trigger(TRIGGER_COMMAND, event.provider, outcome, name.replace(" ", "_"))
    logger.info("pr_review_bot.command repository=%s pr=%s command=%s outcome=%s", event.repository, event.pr_id,
                name, outcome)
    return outcome if outcome != "done" else name


__all__ = [
    "EXPLAIN",
    "FIX",
    "HELP_TEXT",
    "IGNORE",
    "PAUSE",
    "RESUME",
    "REVIEW_FULL",
    "WRITE_TESTS",
    "Command",
    "Reply",
    "authorized",
    "handle_comment",
    "parse_command",
]
