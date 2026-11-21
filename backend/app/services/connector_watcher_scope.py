"""Workspace scope of connector watchers, their events, rules and rule decisions.

``require_work_operator`` gates the platform role; on top of it every watcher record is bound to the Workspace in its
``project_id`` under the membership policy of Work items (``secure_work.access.work_scope_project_ids``): a platform
admin is cross-workspace, everyone else sees and manages the records of their own Workspaces only. A record without a
Workspace (a global watcher or rule) applies to every Workspace and is the platform admin's.

The answers never disclose a foreign record: a named Workspace the caller is no member of is the 404 of an unknown id
(``access_control.require_visible_workspace``), and a watcher, event or rule outside the caller's scope is the 404 of
a missing one.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .access_control import require_visible_workspace
from .secure_work.access import work_scope_project_ids

WatcherScope = set[str] | None


async def watcher_scope(db: AsyncSession, user: User) -> WatcherScope:
    """The Workspaces whose watcher records ``user`` reaches; ``None`` is a platform admin (every record)."""
    return await work_scope_project_ids(db, user)


def in_scope(scope: WatcherScope, project_id: str | None) -> bool:
    return scope is None or (bool(project_id) and project_id in scope)


def scope_filter(column: Any, scope: WatcherScope, project_id: str | None) -> Any | None:
    """The listing filter: the named Workspace's records and the global ones for a platform admin; the named one, or
    else all of the caller's Workspaces, for everyone else (``None``: no filter)."""
    if scope is None:
        return ((column == project_id) | column.is_(None)) if project_id else None
    return column == project_id if project_id else column.in_(sorted(scope))


async def require_write_scope(db: AsyncSession, user: User, scope: WatcherScope, project_id: str | None) -> None:
    """The Workspace a watcher or rule is written into: one the caller sees; a global record is admin-only."""
    await require_visible_workspace(db, user.id, project_id)
    if scope is not None and not project_id:
        raise HTTPException(status_code=403, detail="Only a platform admin manages a record for every Workspace")


def require_record(row: Any, scope: WatcherScope, not_found: str) -> Any:
    """``row`` when it exists and lies in ``scope``; else the 404 of a missing record, for both."""
    if row is None or not in_scope(scope, row.project_id):
        raise HTTPException(status_code=404, detail=not_found)
    return row


__all__ = ["WatcherScope", "in_scope", "require_record", "require_write_scope", "scope_filter", "watcher_scope"]
