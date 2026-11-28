"""Workspace scope of connector watchers, their events, rules and rule decisions. A platform admin is cross-workspace
apart from other people's private Workspaces; everyone else sees only the records of their Workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .access_control import require_visible_workspace
from .project.private_workspace import hidden_private_ids
from .secure_work.access import work_scope_project_ids


@dataclass(frozen=True)
class WatcherScope:
    project_ids: frozenset[str] | None
    hidden: frozenset[str] = frozenset()


# Only the secret-authenticated webhook ingress reads with it: every Workspace, no viewer.
SYSTEM_SCOPE = WatcherScope(None)


async def watcher_scope(db: AsyncSession, user: User) -> WatcherScope:
    scope = await work_scope_project_ids(db, user)
    if scope is None:
        return WatcherScope(None, frozenset(await hidden_private_ids(db, user.id)))
    return WatcherScope(frozenset(scope))


def in_scope(scope: WatcherScope, project_id: str | None) -> bool:
    if scope.project_ids is None:
        return (project_id or "") not in scope.hidden
    return bool(project_id) and project_id in scope.project_ids


def scope_filter(column: Any, scope: WatcherScope, project_id: str | None) -> Any:
    if scope.project_ids is None:
        visible = column.not_in(sorted(scope.hidden))
        return (((column == project_id) & visible) if project_id else visible) | column.is_(None)
    return column == project_id if project_id else column.in_(sorted(scope.project_ids))


async def require_write_scope(db: AsyncSession, user: User, scope: WatcherScope, project_id: str | None) -> None:
    # A global record is admin-only.
    await require_visible_workspace(db, user.id, project_id)
    if scope.project_ids is not None and not project_id:
        raise HTTPException(status_code=403, detail="Only a platform admin manages a record for every Workspace")


def require_record(row: Any, scope: WatcherScope, not_found: str) -> Any:
    # A record outside the scope gets the 404 of a missing one.
    if row is None or not in_scope(scope, row.project_id):
        raise HTTPException(status_code=404, detail=not_found)
    return row


__all__ = ["SYSTEM_SCOPE", "WatcherScope", "in_scope", "require_record", "require_write_scope", "scope_filter",
           "watcher_scope"]
