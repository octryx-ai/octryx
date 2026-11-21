"""Admin edits of functions (with their tool sets) and roles. Every edit is audited.

Roles grant execution authority and are edited here, on the Roles admin screen, with an audit
log — not through a Rules publish with approval: too much security blocks the system.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.work_role_model import (
    DELIVERY_ALL,
    DELIVERY_SELECTED,
    GLOBAL_SCOPE,
    WorkRole,
    WorkRoleAssignment,
    WorkRoleFunction,
    WorkRoleFunctionLink,
)
from ...time_utils import utc_now
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE, require_visible_workspace, workspace_visible
from . import audit
from .catalog_scope import (
    CallerScope,
    assignment_counts,
    connection_names,
    functions_of,
    role_keys_by_function,
    visible_connection_ids,
)
from .errors import WorkRoleError, require_scope_admin, version_conflict
from .seeds import PROTECTED_FUNCTIONS
from .tool_sets import ToolSetError, normalize_entries

KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _key(raw: object) -> str:
    key = str(raw or "").strip()
    if not KEY.match(key):
        raise WorkRoleError("invalid_key", "A key is 2-40 characters: lower-case letters, digits and _, starting "
                            "with a letter.", 422)
    return key


def _name(raw: object) -> str:
    name = str(raw or "").strip()
    if not name or len(name) > 120:
        raise WorkRoleError("invalid_name", "A name has 1-120 characters.", 422)
    return name


def _entries(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise WorkRoleError("invalid_tools", "tools must be a list of tool names and selectors.", 422)
    try:
        return normalize_entries(raw)
    except ToolSetError as error:
        raise WorkRoleError("invalid_tool_entry", str(error), 422, entry=error.entry) from None


async def _workspace(db: AsyncSession, user: User, workspace_id: str | None) -> str | None:
    """The Workspace a function or role is scoped to: an unknown one and one the caller is no member of are the same
    404 ``project_not_found``, before the scope admin rule answers."""
    if workspace_id is None:
        return None
    try:
        await require_visible_workspace(db, user.id, str(workspace_id))
    except HTTPException:
        raise WorkRoleError("project_not_found", WORKSPACE_NOT_FOUND_MESSAGE, 404) from None
    return str(workspace_id)


async def _visible(db: AsyncSession, user: User, row: Any, missing: WorkRoleError) -> Any:
    """A function or role by id: a missing one and one of a Workspace the caller does not see are the same 404, so an
    outsider learns neither its existence nor its tool set; a global one is everyone's catalog."""
    if row is None or (row.project_id and not await workspace_visible(db, user.id, row.project_id)):
        raise missing
    return row


# --- functions ------------------------------------------------------------------------------------------------------

def _function_scope(workspace_id: str | None) -> Any:
    if workspace_id is None:
        return WorkRoleFunction.project_id.is_(None)
    return WorkRoleFunction.project_id.is_(None) | (WorkRoleFunction.project_id == workspace_id)


async def _role_keys(db: AsyncSession, user: User, row: WorkRoleFunction) -> list[str]:
    return (await role_keys_by_function(db, CallerScope(db, user), [row.id])).get(row.id, [])


def function_view(row: WorkRoleFunction, role_keys: list[str] | None = None) -> dict[str, Any]:
    return {"id": row.id, "key": row.key, "name": row.name, "description": row.description or "",
            "workspace_id": row.project_id, "built_in": bool(row.built_in), "tools": list(row.tools_json or []),
            "tools_version": row.tools_version, "version": row.version, "role_keys": role_keys or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def list_functions(db: AsyncSession, user: User, workspace_id: str | None) -> list[dict[str, Any]]:
    """The global functions, and those of a named Workspace the caller sees (else 404 ``project_not_found``)."""
    workspace_id = await _workspace(db, user, workspace_id)
    query = select(WorkRoleFunction).where(_function_scope(workspace_id))
    rows = (await db.execute(query.order_by(WorkRoleFunction.built_in.desc(), WorkRoleFunction.key))).scalars().all()
    keys = await role_keys_by_function(db, CallerScope(db, user), [row.id for row in rows], workspace_id)
    return [function_view(row, keys.get(row.id)) for row in rows]


async def visible_function(db: AsyncSession, user: User, function_id: str) -> WorkRoleFunction:
    return await _visible(db, user, await db.get(WorkRoleFunction, function_id, populate_existing=True),
                          WorkRoleError("function_not_found", "Function not found.", 404))


async def create_function(db: AsyncSession, user: User, body: dict[str, Any]) -> dict[str, Any]:
    workspace_id = await _workspace(db, user, body.get("workspace_id"))
    await require_scope_admin(db, user, workspace_id, "functions")
    row = WorkRoleFunction(key=_key(body.get("key")), name=_name(body.get("name")),
                           description=str(body.get("description") or ""), project_id=workspace_id,
                           scope_key=workspace_id or GLOBAL_SCOPE, tools_json=_entries(body.get("tools") or []),
                           created_by=user.id, updated_by=user.id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise WorkRoleError("function_exists", f"A function with key '{row.key}' exists here.", 409) from None
    audit.record(db, actor_id=user.id, action="function.created", target_type="function", target_id=row.id,
                 label=row.name, workspace_id=workspace_id, after=function_view(row))
    await db.flush()
    return function_view(row)


async def update_function(db: AsyncSession, user: User, function_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = await visible_function(db, user, function_id)
    await require_scope_admin(db, user, row.project_id, "functions")
    if body.get("expected_version") != row.version:
        raise version_conflict("function")
    before = function_view(row)
    if "name" in body:
        row.name = _name(body["name"])
    if "description" in body:
        row.description = str(body.get("description") or "")
    row.version += 1
    row.updated_by, row.updated_at = user.id, utc_now()
    audit.record(db, actor_id=user.id, action="function.updated", target_type="function", target_id=row.id,
                 label=row.name, workspace_id=row.project_id, before=before, after=function_view(row))
    await db.flush()
    return function_view(row, await _role_keys(db, user, row))


async def set_function_tools(db: AsyncSession, user: User, function_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = await visible_function(db, user, function_id)
    await require_scope_admin(db, user, row.project_id, "function tool sets")
    if body.get("expected_tools_version") != row.tools_version:
        raise version_conflict("tool set")
    before = list(row.tools_json or [])
    row.tools_json = _entries(body.get("tools"))
    row.tools_version += 1
    row.updated_by, row.updated_at = user.id, utc_now()
    audit.record(db, actor_id=user.id, action="function.tools_changed", target_type="function", target_id=row.id,
                 label=row.name, workspace_id=row.project_id, before={"tools": before, "tools_version":
                 row.tools_version - 1}, after={"tools": row.tools_json, "tools_version": row.tools_version})
    await db.flush()
    return function_view(row, await _role_keys(db, user, row))


async def delete_function(db: AsyncSession, user: User, function_id: str) -> None:
    row = await visible_function(db, user, function_id)
    await require_scope_admin(db, user, row.project_id, "functions")
    if row.built_in:
        raise WorkRoleError("function_built_in", "A built-in function cannot be deleted.", 409)
    roles = await _role_keys(db, user, row)
    audit.record(db, actor_id=user.id, action="function.deleted", target_type="function", target_id=row.id,
                 label=row.name, workspace_id=row.project_id, before={**function_view(row, roles)})
    await db.execute(delete(WorkRoleFunctionLink).where(WorkRoleFunctionLink.function_id == row.id))
    await db.delete(row)
    await db.flush()


# --- roles ----------------------------------------------------------------------------------------------------------

def role_view(row: WorkRole, functions: list[tuple[str, str]], assignment_count: int,
              connections: dict[str, str]) -> dict[str, Any]:
    """``connections``: the display names of the role's connections the viewer may see (``catalog_scope``); the
    stored ids outside it are not serialized, neither as id nor as name."""
    policy = dict(row.command_policy_json or {})
    shown = [cid for cid in row.connection_ids_json or [] if cid in connections]
    return {"id": row.id, "key": row.key, "name": row.name, "description": row.description or "",
            "workspace_id": row.project_id, "built_in": bool(row.built_in), "is_active": bool(row.is_active),
            "function_keys": [key for key, _ in functions],
            "functions": [{"key": key, "name": name} for key, name in functions],
            "delivery_connections": row.delivery_connections or DELIVERY_ALL,
            "connection_ids": shown,
            "connections": [{"id": cid, "name": connections[cid]} for cid in shown],
            "trusted": bool(row.trusted),
            "trusted_changed_by": row.trusted_changed_by,
            "trusted_changed_at": row.trusted_changed_at.isoformat() if row.trusted_changed_at else None,
            "command_policy": {"allow": list(policy.get("allow") or []), "deny": list(policy.get("deny") or [])},
            "version": row.version, "assignment_count": assignment_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def _views(db: AsyncSession, user: User, rows: list[WorkRole],
                 workspace_id: str | None = None) -> list[dict[str, Any]]:
    """Role views whose related rows (function names, assignment counts, connections) are scoped to what the caller
    sees (``catalog_scope``). A Workspace role shows the connections available in its Workspace; a global role those
    available in ``workspace_id`` when the view addresses one Workspace, else those the caller sees."""
    ids, scope = [row.id for row in rows], CallerScope(db, user)
    functions, counts = await functions_of(db, ids), await assignment_counts(db, scope, ids)
    names: dict[str, dict[str, str]] = {}
    for row in rows:
        names[row.id] = await connection_names(db, scope, list(row.connection_ids_json or []),
                                               row.project_id or workspace_id)
    return [role_view(row, functions.get(row.id, []), counts.get(row.id, 0), names[row.id]) for row in rows]


async def list_roles(db: AsyncSession, user: User, workspace_id: str | None) -> list[dict[str, Any]]:
    """The global roles, and those of a named Workspace the caller sees (else 404 ``project_not_found``)."""
    workspace_id = await _workspace(db, user, workspace_id)
    scope = (WorkRole.project_id.is_(None) if workspace_id is None
             else (WorkRole.project_id.is_(None) | (WorkRole.project_id == workspace_id)))
    rows = list((await db.execute(select(WorkRole).where(scope).order_by(WorkRole.built_in.desc(), WorkRole.name))
                 ).scalars().all())
    return await _views(db, user, rows, workspace_id)


async def _role(db: AsyncSession, user: User, role_id: str) -> WorkRole:
    return await _visible(db, user, await db.get(WorkRole, role_id, populate_existing=True),
                          WorkRoleError("role_not_found", "Role not found.", 404))


async def _role_view(db: AsyncSession, user: User, role_id: str) -> dict[str, Any]:
    return (await _views(db, user, [await db.get(WorkRole, role_id, populate_existing=True)]))[0]


async def get_role(db: AsyncSession, user: User, role_id: str) -> dict[str, Any]:
    return (await _views(db, user, [await _role(db, user, role_id)]))[0]


async def _function_ids(db: AsyncSession, keys: object, workspace_id: str | None) -> dict[str, str]:
    if not isinstance(keys, list):
        raise WorkRoleError("invalid_functions", "function_keys must be a list of function keys.", 422)
    wanted = list(dict.fromkeys(str(key) for key in keys))
    rows = (await db.execute(select(WorkRoleFunction).where(_function_scope(workspace_id),
                                                            WorkRoleFunction.key.in_(wanted)))).scalars().all()
    # A Workspace's own function wins over a global one with the same key.
    found = {row.key: row.id for row in sorted(rows, key=lambda item: item.project_id is not None)}
    missing = [key for key in wanted if key not in found]
    if missing:
        raise WorkRoleError("unknown_function", f"Unknown function(s): {', '.join(missing)}.", 422, keys=missing)
    return {key: found[key] for key in wanted}


async def _set_functions(db: AsyncSession, role: WorkRole, keys: object) -> list[str]:
    ids = await _function_ids(db, keys, role.project_id)
    kept = PROTECTED_FUNCTIONS.get(role.key, frozenset()) if role.built_in else frozenset()
    lost = sorted(kept - set(ids))
    if lost:
        raise WorkRoleError("role_keeps_function", f"The built-in role '{role.name}' keeps {', '.join(lost)}: it "
                            "keeps the Workspace manageable.", 409, functions=lost)
    await db.execute(delete(WorkRoleFunctionLink).where(WorkRoleFunctionLink.role_id == role.id))
    for function_id in ids.values():
        db.add(WorkRoleFunctionLink(role_id=role.id, function_id=function_id))
    await db.flush()
    return sorted(ids)


async def _apply_delivery(db: AsyncSession, user: User, role: WorkRole, body: dict[str, Any]) -> None:
    if "delivery_connections" in body:
        mode = body["delivery_connections"]
        if mode not in (DELIVERY_ALL, DELIVERY_SELECTED):
            raise WorkRoleError("invalid_delivery", "delivery_connections is 'all' or 'selected'.", 422)
        role.delivery_connections = mode
    if "connection_ids" in body:
        ids = body["connection_ids"]
        if not isinstance(ids, list):
            raise WorkRoleError("invalid_connections", "connection_ids must be a list.", 422)
        wanted = list(dict.fromkeys(str(item) for item in ids))
        scope = CallerScope(db, user)
        # A connection not available to the role's scope answers like an unknown one.
        known = await visible_connection_ids(db, scope, wanted, role.project_id)
        missing = [item for item in wanted if item not in known]
        if missing:
            raise WorkRoleError("unknown_connection", "Unknown connection id(s).", 422, connection_ids=missing)
        # The stored links the caller cannot see are not in its view, so its list never removes them.
        stored = [str(item) for item in role.connection_ids_json or []]
        shown = await visible_connection_ids(db, scope, stored, role.project_id)
        role.connection_ids_json = wanted + [item for item in stored if item not in shown and item not in wanted]


def _command_policy(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        raise WorkRoleError("invalid_command_policy", "command_policy is {allow: [...], deny: [...]}.", 422)
    policy = {}
    for key in ("allow", "deny"):
        values = raw.get(key) or []
        if not isinstance(values, list) or any(not str(item).strip() for item in values):
            raise WorkRoleError("invalid_command_policy", f"command_policy.{key} is a list of command patterns.", 422)
        policy[key] = list(dict.fromkeys(str(item).strip() for item in values))
    return policy


async def create_role(db: AsyncSession, user: User, body: dict[str, Any]) -> dict[str, Any]:
    workspace_id = await _workspace(db, user, body.get("workspace_id"))
    await require_scope_admin(db, user, workspace_id, "roles")
    row = WorkRole(key=_key(body.get("key")), name=_name(body.get("name")),
                   description=str(body.get("description") or ""), project_id=workspace_id,
                   scope_key=workspace_id or GLOBAL_SCOPE, trusted=False,
                   command_policy_json=_command_policy(body.get("command_policy") or {}),
                   created_by=user.id, updated_by=user.id)
    await _apply_delivery(db, user, row, body)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise WorkRoleError("role_exists", f"A role with key '{row.key}' exists here.", 409) from None
    await _set_functions(db, row, body.get("function_keys") or [])
    view = await _role_view(db, user, row.id)
    audit.record(db, actor_id=user.id, action="role.created", target_type="role", target_id=row.id, label=row.name,
                 workspace_id=workspace_id, after=view)
    await db.flush()
    return view


async def update_role(db: AsyncSession, user: User, role_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = await _role(db, user, role_id)
    await require_scope_admin(db, user, row.project_id, "roles")
    if body.get("expected_version") != row.version:
        raise version_conflict("role")
    before = await _role_view(db, user, row.id)
    if "name" in body:
        row.name = _name(body["name"])
    if "description" in body:
        row.description = str(body.get("description") or "")
    if "is_active" in body:
        row.is_active = bool(body["is_active"])
    if "command_policy" in body:
        row.command_policy_json = _command_policy(body["command_policy"])
    await _apply_delivery(db, user, row, body)
    if "function_keys" in body:
        await _set_functions(db, row, body["function_keys"])
    row.version += 1
    row.updated_by, row.updated_at = user.id, utc_now()
    await db.flush()
    after = await _role_view(db, user, row.id)
    audit.record(db, actor_id=user.id, action="role.updated", target_type="role", target_id=row.id, label=row.name,
                 workspace_id=row.project_id, before=before, after=after)
    await db.flush()
    return after


async def set_trusted(db: AsyncSession, user: User, role_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """The trusted role: an explicit opt-in, off by default, audited with a reason."""
    row = await _role(db, user, role_id)
    await require_scope_admin(db, user, row.project_id, "the trusted flag")
    if body.get("expected_version") != row.version:
        raise version_conflict("role")
    trusted = body.get("trusted")
    if not isinstance(trusted, bool):
        raise WorkRoleError("invalid_trusted", "trusted is true or false.", 422)
    reason = str(body.get("reason") or "").strip()
    if trusted and not reason:
        raise WorkRoleError("reason_required", "Say why this role may write without per-call confirmation.", 422)
    before = bool(row.trusted)
    if before != trusted:
        row.trusted = trusted
        row.trusted_changed_by, row.trusted_changed_at = user.id, utc_now()
        row.version += 1
        row.updated_by, row.updated_at = user.id, utc_now()
        audit.record(db, actor_id=user.id, action="role.trusted_changed", target_type="role", target_id=row.id,
                     label=row.name, workspace_id=row.project_id, before={"trusted": before},
                     after={"trusted": trusted}, reason=reason or None)
        await db.flush()
    return await _role_view(db, user, row.id)


async def delete_role(db: AsyncSession, user: User, role_id: str) -> None:
    row = await _role(db, user, role_id)
    await require_scope_admin(db, user, row.project_id, "roles")
    if row.built_in:
        raise WorkRoleError("role_built_in", "A built-in role cannot be deleted; take its functions away instead.",
                            409)
    count = (await db.execute(select(func.count()).select_from(WorkRoleAssignment).where(
        WorkRoleAssignment.role_id == row.id, WorkRoleAssignment.is_active.is_(True)))).scalar_one()
    if count:
        raise WorkRoleError("role_in_use", f"{count} active assignment(s) still use this role; revoke them first.",
                            409, assignment_count=count)
    audit.record(db, actor_id=user.id, action="role.deleted", target_type="role", target_id=row.id, label=row.name,
                 workspace_id=row.project_id, before=await _role_view(db, user, row.id))
    await db.execute(delete(WorkRoleFunctionLink).where(WorkRoleFunctionLink.role_id == row.id))
    await db.execute(delete(WorkRoleAssignment).where(WorkRoleAssignment.role_id == row.id))
    await db.delete(row)
    await db.flush()


__all__ = ["create_function", "create_role", "delete_function", "delete_role", "get_role", "list_functions",
           "list_roles", "role_view", "set_function_tools", "set_trusted", "update_function", "update_role"]
