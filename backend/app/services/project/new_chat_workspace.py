"""The Workspace a new chat starts in: never an archived one."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from .default_workspace import default_workspace_id
from .service import get_user_project_ids


async def is_archived_workspace(db: AsyncSession, project_id: str) -> bool:
    found = (
        await db.execute(select(Project.id).where(Project.id == project_id, Project.is_active.is_(False)))
    ).scalar_one_or_none()
    return found is not None


async def active_member_workspace_ids(db: AsyncSession, *, user: User) -> list[str]:
    member_ids = [str(project_id) for project_id in await get_user_project_ids(user.id, db)]
    if not member_ids:
        return []
    rows = await db.execute(
        select(Project.id).where(Project.id.in_(member_ids), Project.is_active.is_(True)).order_by(Project.name.asc())
    )
    return [str(project_id) for project_id in rows.scalars()]


async def fallback_new_chat_workspace(
    db: AsyncSession, *, user: User, active_workspace_ids: Iterable[str] | None = None
) -> str:
    candidates = (
        list(active_workspace_ids)
        if active_workspace_ids is not None
        else await active_member_workspace_ids(db, user=user)
    )
    from .private_workspace import owned_private_workspace  # noqa: PLC0415

    own = await owned_private_workspace(db, str(user.id))  # the person's private Workspace comes first
    if own is not None and own.is_active and (active_workspace_ids is None or own.id in candidates):
        return own.id
    default_id = await default_workspace_id(db)
    if default_id and default_id in candidates:
        return default_id
    return candidates[0] if len(candidates) == 1 else ""


async def new_chat_workspace(
    db: AsyncSession, *, user: User, project_id: str, active_workspace_ids: Iterable[str] | None = None
) -> str:
    requested = str(project_id or "").strip()
    if requested and not await is_archived_workspace(db, requested):
        return requested
    fallback = await fallback_new_chat_workspace(db, user=user, active_workspace_ids=active_workspace_ids)
    if fallback or requested:
        return fallback
    from .private_workspace import ensure_private_workspace  # noqa: PLC0415

    # No choice at all: the person's private Workspace, created on first use (defaults work).
    return (await ensure_private_workspace(db, user)).id


__all__ = [
    "active_member_workspace_ids",
    "fallback_new_chat_workspace",
    "is_archived_workspace",
    "new_chat_workspace",
]
