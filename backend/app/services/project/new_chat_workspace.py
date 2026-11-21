"""The Workspace a new chat starts in: never an archived one.

After a fresh login the chat opens the person's latest thread. When that thread lives in a Workspace that was
archived since, the chat's Workspace would be that archived one, and
"New chat" would pass it on (``/chat/api/bootstrap?new=1&project_id=<archived>``), so the new chat would be created
there although the person had chosen another Workspace. A new chat therefore starts in an active Workspace only:

- the requested Workspace unless it is archived (an unknown id is left to the turn's access check);
- else the Instance's default Workspace (``make-default``) when the person is a member of it;
- else the person's only active Workspace;
- else none (``""``): a global admin may chat without one, everyone else is asked to choose.

An existing thread keeps its own Workspace, archived or not; this only decides where a new one starts.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from .default_workspace import default_workspace_id
from .service import get_user_project_ids


async def is_archived_workspace(db: AsyncSession, project_id: str) -> bool:
    """True for a Workspace that exists and is archived (inactive); an unknown id is left to access checks."""
    found = (
        await db.execute(select(Project.id).where(Project.id == project_id, Project.is_active.is_(False)))
    ).scalar_one_or_none()
    return found is not None


async def active_member_workspace_ids(db: AsyncSession, *, user: User) -> list[str]:
    """The person's active Workspaces (membership direct or through a group), by name."""
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
    """The default Workspace when the person is in it, else their only active Workspace, else ``""``.

    ``active_workspace_ids`` are the person's active Workspaces when the caller already has them.
    """
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
    """``project_id`` unless it names an archived Workspace; that one is replaced by the fallback above.

    An unknown id is kept: the turn's access check refuses it.
    """
    requested = str(project_id or "").strip()
    if not requested or not await is_archived_workspace(db, requested):
        return requested
    return await fallback_new_chat_workspace(db, user=user, active_workspace_ids=active_workspace_ids)


__all__ = [
    "active_member_workspace_ids",
    "fallback_new_chat_workspace",
    "is_archived_workspace",
    "new_chat_workspace",
]
