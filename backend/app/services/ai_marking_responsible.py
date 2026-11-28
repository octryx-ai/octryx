"""The person an agent's outgoing text names as responsible (anti-slop E: agent work is marked, a person owns it)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

HUMAN = "human"


async def _human(db: AsyncSession, user_id: str | None) -> Any:
    from ..models import User

    if not user_id:
        return None
    user = await db.get(User, user_id)
    return user if user is not None and getattr(user, "account_type", HUMAN) == HUMAN else None


def display_name(user: Any) -> str:
    return str(getattr(user, "display_name", "") or getattr(user, "username", "") or "").strip()


async def _bot_enabler(db: AsyncSession, run: Any) -> str | None:
    from ..models import AuditLog
    from .pr_review_bot.settings import TRIGGER_OFF, repository_record

    record = await repository_record(db, run.project_id, str(run.repository or ""))
    if record is None:
        return None
    rows = (await db.execute(
        select(AuditLog.user_id, AuditLog.details)
        .where(AuditLog.resource_type == "code_repository", AuditLog.resource_id == record.id,
               AuditLog.action == "pr_review_bot.settings_changed")
        .order_by(AuditLog.created_at.desc())
    )).all()
    for user_id, details in rows:
        trigger = dict(dict(details or {}).get("settings") or {}).get("trigger")
        if trigger and trigger != TRIGGER_OFF:
            return user_id
    return None


async def _workspace_admin(db: AsyncSession, project_id: str | None) -> str | None:
    from .problems.alerts import _workspace_admins

    admins = await _workspace_admins(db, project_id)
    return admins[0] if admins else None


async def _review_bot_responsible(db: AsyncSession, run: Any) -> Any:
    from .pr_review_bot.starter import CONTEXT_KEY

    # An @octryx command names its commenter; an automatic review names who switched the bot on.
    commenter = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get("requested_by")
    for candidate in (commenter, await _bot_enabler(db, run), await _workspace_admin(db, run.project_id)):
        user = await _human(db, candidate)
        if user is not None:
            return user
    return None


async def run_responsible(db: AsyncSession, run: Any) -> Any:
    from ..models import User
    from .pr_review_bot.bot_user import ACCOUNT_TYPE_REVIEW_BOT

    requester = await db.get(User, run.requested_by)
    if getattr(requester, "account_type", None) == ACCOUNT_TYPE_REVIEW_BOT:
        return await _review_bot_responsible(db, run)
    for candidate in (run.responsible_user_id, run.requested_by):
        user = await _human(db, candidate)
        if user is not None:
            return user
    return await _human(db, await _workspace_admin(db, run.project_id))


async def responsible_name(db: AsyncSession, *, run: Any = None, user_id: str | None = None,
                           session_id: str | None = None) -> str | None:
    from .workflow_runs.records import active_run_for_session

    run = run if run is not None else await active_run_for_session(db, session_id)
    user = await run_responsible(db, run) if run is not None else await _human(db, user_id)
    name = display_name(user) if user is not None else ""
    return name or None
