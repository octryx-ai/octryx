"""A person's answer in a finding's thread reaches the next pass.

Otherwise a reply such as "coupons are applied by the checkout service, never in order_total" is kept as a
correction only, and the next incremental pass repeats the finding word for word. So the reply is remembered on
the open finding of the pull request's last posted pass (``open_findings[].replies``, the last
``verdict.MAX_REPLIES``); ``incremental.seed`` hands it to the follow-up review, which answers ``withdrawn`` unless it
names new evidence (``convergence.FOLLOW_UP_RULE``).

Only a person counts, by the same rule as a correction (``corrections.sources.pr_comment``): no command, none of
the bot's own posts, an author linked to an active human with a role in the Workspace. Each comment once.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..workflow_runs.review.verdict import MAX_REPLIES, MAX_REPLY_CHARS
from .comment_events import CommentEvent
from .starter import CONTEXT_KEY


async def _person(db: AsyncSession, project_id: str, event: CommentEvent) -> bool:
    from ..access_control import get_project_role_for_user
    from ..workflow_runs.corrections.signature import data
    from .commands import parse_command
    from .seat_choice import linked_users

    body, bot_bodies = event.body.strip(), data()["pr_comment"]["bot_bodies"]
    if parse_command(body) is not None or any(re.match(pattern, body) for pattern in bot_bodies):
        return False
    for user in await linked_users(db, event.repository, event.author, event.author_id):
        if user.account_type == "human" and await get_project_role_for_user(db, user.id, project_id):
            return True
    return False


async def remember(db: AsyncSession, project_id: str, event: CommentEvent) -> bool:
    """Keep ``event`` on the open finding whose thread it answers; whether it was kept (the caller commits)."""
    from .ignore import last_posted

    if not event.inline or not event.body.strip():
        return False
    run = await last_posted(db, project_id, event.repository, event.pr_id)
    facts = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}) if run is not None else {}
    findings = [dict(item) for item in facts.get("open_findings") or [] if isinstance(item, dict)]
    finding = next((item for item in findings if str(item.get("comment_id") or "") == event.thread_root), None)
    if finding is None or event.comment_id in (finding.get("reply_ids") or []):
        return False
    if not await _person(db, project_id, event):
        return False
    finding["replies"] = [*(finding.get("replies") or []), event.body.strip()[:MAX_REPLY_CHARS]][-MAX_REPLIES:]
    finding["reply_ids"] = [*(finding.get("reply_ids") or []), event.comment_id][-20:]
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {**facts, "open_findings": findings}}
    return True


__all__ = ["remember"]
