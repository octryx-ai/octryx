"""``token`` problems: stored credentials that expired or expire within 14 days (``stored_secrets.expires_at``).

An expired credential is a problem, one that expires within 14 days needs attention; ``since`` and ``last_seen``
are ``expires_at`` (a rotation moves it, so an acknowledged expiry comes back for the new date). The fix is the
place the credential belongs to: the model provider that references it, otherwise its connection.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider, StoredSecret
from .links import TARGET_CONNECTION, TARGET_PROVIDER, fix_link
from .model import KIND_TOKEN, SEVERITY_ATTENTION, SEVERITY_PROBLEM, CollectContext, Problem, workspace_of

EXPIRES_SOON = timedelta(days=14)


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    rows = (await db.execute(
        select(StoredSecret, LLMProvider.id)
        .outerjoin(LLMProvider, LLMProvider.api_key_secret_ref == StoredSecret.id)
        .where(StoredSecret.expires_at.is_not(None), StoredSecret.expires_at < ctx.now + EXPIRES_SOON,
               ctx.scope(func.coalesce(StoredSecret.project_id, "")))
        .order_by(StoredSecret.expires_at.asc()).limit(ctx.limit)
    )).all()
    problems, seen = [], set()
    for secret, provider_id in rows:
        if secret.id in seen:
            continue
        seen.add(secret.id)
        expired = secret.expires_at < ctx.now
        workspace_id = workspace_of(secret.project_id)
        fix = (fix_link(TARGET_PROVIDER, object_id=provider_id) if provider_id
               else fix_link(TARGET_CONNECTION, workspace_id=workspace_id, object_id=secret.tool_name))
        problems.append(Problem(
            kind=KIND_TOKEN, severity=SEVERITY_PROBLEM if expired else SEVERITY_ATTENTION, object_type="secret",
            object_id=secret.id, object_name=secret.name, reason_code="expired" if expired else "expires_soon",
            title=(f"Credential {secret.name} has expired." if expired
                   else f"Credential {secret.name} expires within 14 days."),
            since=secret.expires_at, last_seen=secret.expires_at, workspace_id=workspace_id, fix=fix,
        ))
    return problems


__all__ = ["EXPIRES_SOON", "collect"]
