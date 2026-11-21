"""The related rows of a Work-role catalog view, scoped to what the caller sees.

A function or role the caller sees can be linked to rows of Workspaces the caller does not see: a role of a foreign
Workspace that uses a global function, a global role assigned in a foreign Workspace, a connection available only in
a foreign Workspace, or a foreign Workspace's function sharing a key with a global one. Every reader here returns only
rows that are global or bound to a Workspace the caller sees (``access_control.workspace_visible``; a platform admin
sees every existing Workspace), so an outsider learns nothing about a foreign Workspace from a catalog view. A view
addressed to one Workspace (a Workspace's role listing, the effective permission there) narrows connections further to
those available in that Workspace.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.named_connection import ConnectorNamedConnection
from ...models.runtime.work_role_model import WorkRole, WorkRoleAssignment, WorkRoleFunction, WorkRoleFunctionLink
from ..access_control import workspace_visible
from ..config_effective import AVAILABLE_ALL, available
from ..named_connections.grants import connection_workspace_ids, subject_of


class CallerScope:
    """The Workspaces one caller sees, asked once per Workspace id and remembered for one request."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self._db, self._user, self._seen = db, user, {}

    async def sees(self, workspace_id: str | None) -> bool:
        if workspace_id is None:
            return True
        if workspace_id not in self._seen:
            self._seen[workspace_id] = await workspace_visible(self._db, self._user.id, workspace_id)
        return self._seen[workspace_id]

    async def visible(self, workspace_ids: Iterable[str | None]) -> set[str]:
        return {wid for wid in set(workspace_ids) if wid is not None and await self.sees(wid)}


async def role_keys_by_function(db: AsyncSession, scope: CallerScope, function_ids: list[str],
                                workspace_id: str | None = None) -> dict[str, list[str]]:
    """The keys of the roles using each function: global roles and roles of Workspaces the caller sees; with
    ``workspace_id`` (a listing filtered to one Workspace) only global roles and that Workspace's roles."""
    if not function_ids:
        return {}
    rows = (await db.execute(select(WorkRoleFunctionLink.function_id, WorkRole.key, WorkRole.project_id).join(
        WorkRole, WorkRole.id == WorkRoleFunctionLink.role_id).where(
        WorkRoleFunctionLink.function_id.in_(function_ids)))).all()
    seen = await scope.visible(project_id for _, _, project_id in rows)
    found: dict[str, list[str]] = {}
    for function_id, key, project_id in rows:
        if project_id is not None and (project_id not in seen or workspace_id not in (None, project_id)):
            continue
        found.setdefault(function_id, []).append(key)
    return {fid: sorted(keys) for fid, keys in found.items()}


async def functions_of(db: AsyncSession, role_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """The (key, name) of each role's functions, read from the linked rows themselves (a role links only global
    functions and its own Workspace's functions), so a foreign function of the same key never names one."""
    if not role_ids:
        return {}
    rows = (await db.execute(select(WorkRoleFunctionLink.role_id, WorkRoleFunction.key, WorkRoleFunction.name).join(
        WorkRoleFunction, WorkRoleFunction.id == WorkRoleFunctionLink.function_id).where(
        WorkRoleFunctionLink.role_id.in_(role_ids)))).all()
    found: dict[str, list[tuple[str, str]]] = {}
    for role_id, key, name in rows:
        found.setdefault(role_id, []).append((key, name))
    return {rid: sorted(items) for rid, items in found.items()}


async def function_names(db: AsyncSession, workspace_id: str) -> dict[str, str]:
    """Display names by function key in one Workspace: its global functions and its own, its own winning."""
    rows = (await db.execute(select(WorkRoleFunction.key, WorkRoleFunction.name, WorkRoleFunction.project_id).where(
        WorkRoleFunction.project_id.is_(None) | (WorkRoleFunction.project_id == workspace_id)))).all()
    return {key: name for key, name, _ in sorted(rows, key=lambda row: row[2] is not None)}


async def assignment_counts(db: AsyncSession, scope: CallerScope, role_ids: list[str]) -> dict[str, int]:
    """Active assignments per role in the Workspaces the caller sees (a global role is assigned per Workspace)."""
    if not role_ids:
        return {}
    rows = (await db.execute(select(WorkRoleAssignment.role_id, WorkRoleAssignment.project_id, func.count()).where(
        WorkRoleAssignment.role_id.in_(role_ids), WorkRoleAssignment.is_active.is_(True))
        .group_by(WorkRoleAssignment.role_id, WorkRoleAssignment.project_id))).all()
    seen = await scope.visible(project_id for _, project_id, _ in rows)
    counts: dict[str, int] = {}
    for role_id, project_id, count in rows:
        if project_id in seen:
            counts[role_id] = counts.get(role_id, 0) + count
    return counts


async def _visible_connections(db: AsyncSession, scope: CallerScope, ids: list[str],
                               workspace_id: str | None) -> list[ConnectorNamedConnection]:
    if not ids:
        return []
    rows = (await db.execute(select(ConnectorNamedConnection).where(ConnectorNamedConnection.id.in_(ids)))
            ).scalars().all()
    workspaces = await connection_workspace_ids(db, [str(row.id) for row in rows])
    found = []
    for row in rows:
        subject = subject_of(row, workspaces[str(row.id)])
        if workspace_id:
            targets = {workspace_id}
        else:
            targets = await scope.visible((*subject.workspace_ids, subject.owner_workspace_id))
        if subject.available_in == AVAILABLE_ALL or any(available(subject, target) for target in targets):
            found.append(row)
    return found


async def visible_connection_ids(db: AsyncSession, scope: CallerScope, ids: list[str],
                                 workspace_id: str | None) -> set[str]:
    """The connection ids among ``ids`` a role may name: with ``workspace_id`` (a Workspace role) those available in
    that Workspace; for a global role those available everywhere or in a Workspace the caller sees."""
    return {str(row.id) for row in await _visible_connections(db, scope, ids, workspace_id)}


async def connection_names(db: AsyncSession, scope: CallerScope, ids: list[str],
                           workspace_id: str | None = None) -> dict[str, str]:
    """Display names of the connections :func:`visible_connection_ids` admits, by id. A view serializes only these
    ids (``role_view``, ``grant_view``): a foreign, unknown or no longer available connection is left out entirely,
    its id as much as its name and tool."""
    return {str(row.id): f"{row.name} ({row.tool_name})"
            for row in await _visible_connections(db, scope, ids, workspace_id)}


__all__ = ["CallerScope", "assignment_counts", "connection_names", "function_names", "functions_of",
           "role_keys_by_function", "visible_connection_ids"]
