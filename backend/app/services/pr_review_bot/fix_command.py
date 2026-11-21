"""``@octryx fix [claude|codex] [note]`` and ``@octryx write tests [claude|codex] [note]``: which findings,
whether the run may start, and the start in the background (``fix.start_fix``).

- in a finding's thread: that finding (of the pull request's last posted pass); in the conversation: every open
  blocking finding of that pass (``write tests`` needs none);
- refused with one answer when the workflow is switched off (``fix.switched_off``), ``fix.refusal`` names a reason
  or a ``fix`` has nothing to fix;
- the engine is the person's default (choosing one per command is not offered yet); a named other
  engine is answered with that note.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from .comment_events import CommentEvent

logger = logging.getLogger(__name__)
_ENGINE_KEYS = {"claude": "claude_code", "codex": "codex"}


def _findings(facts: dict[str, Any], event: CommentEvent) -> list[dict[str, Any]]:
    open_findings = [dict(item) for item in facts.get("open_findings") or [] if isinstance(item, dict)]
    if event.inline:
        return [item for item in open_findings if str(item.get("comment_id") or "") == event.thread_root]
    return [item for item in open_findings if item.get("severity") in ("high", "medium")
            and not item.get("nonblocking")]


async def _engine_note(db: AsyncSession, user_id: str, project_id: str, engine: str) -> str:
    if not engine:
        return ""
    from ..agent_gateway.engine_policy import effective_engine

    current = (await effective_engine(db, user_id=user_id, workspace_id=project_id)).engine
    if _ENGINE_KEYS.get(engine) == current:
        return ""
    return f" It runs on your default engine ({current}); choosing an engine per command comes later."


async def fix_command(db: AsyncSession, project_id: str, record: CodeRepository, event: CommentEvent, pr: Any,
                      user_id: str, command: Any, reply: Any) -> str:
    from . import fix
    from .commands import WRITE_TESTS
    from .ignore import last_posted

    mode = fix.MODE_TESTS if command.name == WRITE_TESTS else fix.MODE_FIX
    off = await fix.switched_off(db, project_id, mode)
    if off:  # before the repository's own opt-in: switching that on alone would not help
        await reply.post(f"Octryx: {off}", event)
        return "refused"
    refused = await fix.refusal(db, project_id, record, pr)
    run = await last_posted(db, project_id, event.repository, event.pr_id)
    facts = dict(dict(run.context or {}).get("pr_review") or {}) if run is not None else {}
    findings = _findings(facts, event)
    if not refused and mode == fix.MODE_FIX and not findings:
        refused = ("this thread carries no open finding of the last review" if event.inline else
                   "the last review has no open blocking finding to fix")
    if refused:
        await reply.post(f"Octryx: {refused}.", event)
        return "refused"
    engine, note = fix.parse_args(command.args)
    what = "tests" if mode == fix.MODE_TESTS else "a fix of " + ", ".join(str(item.get("id")) for item in findings)
    await reply.post(f"🔧 Octryx is starting a run for {what} on `{pr.source_branch}` (your device and seat when "
                     "available). It answers here when it pushed, or why it did not."
                     + await _engine_note(db, user_id, project_id, engine), event)
    from .commands import spawn

    spawn(_start(project_id, record.id, pr, event, user_id, mode, findings, note, engine))
    return command.name.replace(" ", "_")


async def _start(project_id: str, record_id: str, pr: Any, event: CommentEvent, user_id: str, mode: str,
                 findings: list[dict[str, Any]], note: str, engine: str) -> None:
    from ...db import async_session_factory
    from .fix import start_fix

    async with async_session_factory() as db:
        try:
            await start_fix(db, project_id, pr, event, user_id, mode=mode, findings=findings, note=note,
                            engine=engine)
        except Exception as error:  # noqa: BLE001 - answered in the pull request; the person can ask again
            logger.warning("pr_review_bot.fix_start_failed repository=%s pr=%s", event.repository, event.pr_id,
                           exc_info=True)
            await db.rollback()
            await _answer_failure(db, project_id, record_id, pr, event, str(getattr(error, "message", "") or error))


async def _answer_failure(db: AsyncSession, project_id: str, record_id: str, pr: Any, event: CommentEvent,
                          reason: str) -> None:
    from .bot_user import ensure_review_bot_user
    from .comment_poll import reply_for

    record = await db.get(CodeRepository, record_id)
    if record is None:
        return
    bot = await ensure_review_bot_user(db, project_id)
    reply = reply_for(db, record, bot.id, {pr.pr_id: pr}, event)
    await reply.post(f"Octryx could not start the run: {reason[:300]}.", event)


__all__ = ["fix_command"]
