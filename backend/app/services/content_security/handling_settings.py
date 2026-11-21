"""A Workspace's content handling as its admins see and change it (``GET``/``PUT .../content-handling``).

- :func:`handling_view` — the Workspace's governance alias (``governance_alias``: the one governed model alias every
  ``reroute`` / ``mask_reroute`` kind is sent to, or ``None``) and the governed aliases it may name
  (``governance_aliases``); per kind the effective action on platform model calls with its shipped default
  (``default_action``, possibly ``none``), whether it is the default, the points where
  ``reroute`` / ``mask_reroute`` answers ``content_route_unavailable`` and where it masks instead (the reply
  direction); per enforcement point what the kind's current action actually does there (``surface_defaults``) and
  what each choice would do there before it is saved (``surface_choices``), both from the point table
  (``handling_preview``): e.g. credentials refused on the coding-agent gateway while platform calls mask them,
  mask/reroute left to the model entrance at tool-result receipt, a mask sent for review and a refusal denied by
  Command safety, the Claude Code built-in tool definition report rule and the older-history mask (``conditions``);
  the five actions and per point what the fixed rules do there (``fixed``).
- :func:`set_handling` — one kind's action, or ``default`` (the stored row is deleted); ``reroute`` /
  ``mask_reroute`` need the Workspace's governance alias to be set (422 ``content_handling_alias_required``).
- :func:`set_governance_alias` — the Workspace's governance alias, or ``None`` to clear it: an alias of an active
  gateway catalog (the same aliases content obligations route to, ``policy_engine.runtime.alias_approvals``; else 422
  ``content_handling_alias_unknown``); clearing it while a kind is set to ``reroute`` / ``mask_reroute`` is 409
  ``content_handling_alias_in_use`` (the kinds first).

Refusals carry ``detail.code``. Every change writes an AuditLog row ``content_handling.changed`` (``kind``: the content
kind, or ``governance_alias``) whose old→new is the real transition: edits are serialized (the stored row is read
``FOR UPDATE`` and written only while it still holds the value read; a kind edit to a rerouting action first locks
the governance alias row, as clearing the alias does, so the two cannot interleave); an edit that lost a race (the
row changed or appeared meanwhile) is 409 ``content_handling_conflict`` and changes nothing.

Who may read or change it is the route's rule (``api.routes.workspace_content_handling``).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, WorkspaceContentGovernance, WorkspaceContentHandling
from ...time_utils import utc_now
from ..policy_engine.runtime import alias_approvals
from .handling import (
    ACTIONS,
    KINDS,
    REROUTING,
    SHIPPED_DEFAULTS,
    SURFACE_PLATFORM,
    ContentKind,
    governance_alias,
    workspace_settings,
)
from .handling_preview import fixed_outcomes, reroute_masked_at, reroute_unavailable, surface_actions

ACTION_DEFAULT = "default"
AUDIT_ACTION = "content_handling.changed"
AUDIT_RESOURCE = "workspace_content_handling"
GOVERNANCE_ALIAS = "governance_alias"
CODE_KIND_UNKNOWN = "content_handling_kind_unknown"
CODE_ACTION_INVALID = "content_handling_action_invalid"
CODE_ALIAS_REQUIRED = "content_handling_alias_required"
CODE_ALIAS_UNKNOWN = "content_handling_alias_unknown"
CODE_ALIAS_IN_USE = "content_handling_alias_in_use"
CODE_CONFLICT = "content_handling_conflict"


def _invalid(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def _default(kind: str) -> str:
    return SHIPPED_DEFAULTS[SURFACE_PLATFORM].get(kind, "none")


def _choices(kind: str, settings: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Per choice (each action and ``default``) what it would do at every point, before it is saved."""
    others = {key: value for key, value in settings.items() if key != kind}
    choices = {action: surface_actions(kind, {**others, kind: action}) for action in ACTIONS}
    return {**choices, ACTION_DEFAULT: surface_actions(kind, others)}


def _entry(info: ContentKind, settings: dict[str, str]) -> dict[str, Any]:
    stored = settings.get(info.kind)
    default = _default(info.kind)
    return {"kind": info.kind, "label": info.label, "action": stored or default,
            "default_action": default, "is_default": stored is None,
            "reroute_unavailable": reroute_unavailable(info.kind),
            "reroute_masked_at": reroute_masked_at(info.kind),
            "surface_defaults": surface_actions(info.kind, settings),
            "surface_choices": _choices(info.kind, settings)}


async def governance_aliases(db: AsyncSession) -> list[dict[str, str]]:
    return [{"alias": alias, "label": alias} for alias in sorted(await alias_approvals(db))]


async def handling_view(db: AsyncSession, workspace_id: str, *, can_edit: bool) -> dict[str, Any]:
    settings = await workspace_settings(db, workspace_id)
    return {"workspace_id": workspace_id, "can_edit": can_edit, "actions": list(ACTIONS),
            "governance_alias": await governance_alias(db, workspace_id),
            "governance_aliases": await governance_aliases(db),
            "kinds": [_entry(info, settings) for info in KINDS],
            "fixed": fixed_outcomes()}


async def governance_row(db: AsyncSession, workspace_id: str) -> WorkspaceContentGovernance | None:
    """The Workspace's governance alias row, locked until the edit commits (as :func:`stored_row`)."""
    return (await db.execute(select(WorkspaceContentGovernance).where(
        WorkspaceContentGovernance.workspace_id == workspace_id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def stored_row(db: AsyncSession, workspace_id: str, kind: str) -> WorkspaceContentHandling | None:
    """The stored setting of one Workspace/kind, locked until the edit commits (``FOR UPDATE`` where the database has
    row locks): a concurrent edit of the same kind waits and then reads this edit's value."""
    return (await db.execute(select(WorkspaceContentHandling).where(
        WorkspaceContentHandling.workspace_id == workspace_id, WorkspaceContentHandling.kind == kind)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": CODE_CONFLICT, "message": "This setting was changed at the same time by someone else. Reload it and "
                                          "apply your change again."})


async def _apply(db: AsyncSession, write: Any) -> None:
    """Run one conditional ``write`` (an awaitable returning the result, or ``None`` for an insert): a row created
    meanwhile, or a write that matched no row any more, is :func:`_conflict` and rolls the transaction back."""
    try:
        result = await write
    except IntegrityError:  # created by a concurrent edit meanwhile
        await db.rollback()
        raise _conflict() from None
    if result is not None and result.rowcount != 1:
        await db.rollback()
        raise _conflict()


async def _insert(db: AsyncSession, row: Any) -> None:
    db.add(row)
    await db.flush()


async def _write(db: AsyncSession, row: WorkspaceContentHandling | None, workspace_id: str, kind: str,
                 new: str | None, user_id: str) -> None:
    """Write the change only while the stored row still holds the value read (or is still absent): an edit that
    lost a race changes nothing and is :func:`_conflict`, so the audited old→new is the real transition.

    No savepoint: the write and its AuditLog row are one outer transaction on every backend, committed together by
    the caller (a SQLite savepoint opened outside a driver transaction would commit the write on release). A refused
    write rolls the whole transaction back."""
    table = WorkspaceContentHandling
    if row is None:
        await _apply(db, _insert(db, table(workspace_id=workspace_id, kind=kind, action=new, updated_by=user_id,
                                           updated_at=utc_now())))
        return
    unchanged = (table.id == row.id, table.action == row.action)
    if new is None:
        await _apply(db, db.execute(delete(table).where(*unchanged)))
    else:
        await _apply(db, db.execute(update(table).where(*unchanged).values(
            action=new, updated_by=user_id, updated_at=utc_now())))


def _audit(db: AsyncSession, user_id: str, workspace_id: str, kind: str, old: str | None, new: str | None) -> None:
    db.add(AuditLog(user_id=user_id, action=AUDIT_ACTION, resource_type=AUDIT_RESOURCE,
                    resource_id=f"{workspace_id}:{kind}",
                    details={"workspace_id": workspace_id, "kind": kind, "old": old, "new": new}))


def _label(action: str | None, kind: str) -> str:
    return action if action else f"{ACTION_DEFAULT}({_default(kind)})"


async def set_handling(db: AsyncSession, workspace_id: str, kind: str, body: Any, *, user_id: str) -> dict[str, Any]:
    """Store one kind's action (``default``: delete the row), audit the change; the updated kind entry."""
    info = next((item for item in KINDS if item.kind == kind), None)
    if info is None:
        raise _invalid(CODE_KIND_UNKNOWN, "This content kind is not configurable.")
    action = body.get("action") if isinstance(body, dict) else None
    if action != ACTION_DEFAULT and action not in ACTIONS:
        raise _invalid(CODE_ACTION_INVALID, f"The action is one of {', '.join(ACTIONS)} or {ACTION_DEFAULT}.")
    if action in REROUTING and await governance_row(db, workspace_id) is None:
        raise _invalid(CODE_ALIAS_REQUIRED, "Reroute sends the content to the Workspace's governance alias: set it "
                                            "first.")
    row = await stored_row(db, workspace_id, kind)
    old = row.action if row is not None else None
    new = None if action == ACTION_DEFAULT else action
    if old != new:
        await _write(db, row, workspace_id, kind, new, user_id)
        _audit(db, user_id, workspace_id, kind, _label(old, kind), _label(new, kind))
        await db.flush()
    return _entry(info, await workspace_settings(db, workspace_id))


async def _rerouting_kinds(db: AsyncSession, workspace_id: str) -> list[str]:
    return sorted(kind for kind, action in (await workspace_settings(db, workspace_id)).items()
                  if action in REROUTING)


async def set_governance_alias(db: AsyncSession, workspace_id: str, body: Any, *, user_id: str) -> dict[str, Any]:
    """Store the Workspace's governance alias (``None``: clear it), audit the change; the stored alias."""
    if not isinstance(body, dict) or "alias" not in body:
        raise _invalid(CODE_ALIAS_UNKNOWN, "The body names the governance alias, or null to clear it.")
    alias = body["alias"].strip() if isinstance(body["alias"], str) else body["alias"]
    if alias is not None and (not isinstance(alias, str) or alias not in await alias_approvals(db)):
        raise _invalid(CODE_ALIAS_UNKNOWN, "The alias is not a model alias of an active model gateway.")
    row = await governance_row(db, workspace_id)
    old = row.governance_alias if row is not None else None
    if alias is None and old is not None and (rerouting := await _rerouting_kinds(db, workspace_id)):
        raise HTTPException(status_code=409, detail={
            "code": CODE_ALIAS_IN_USE, "kinds": rerouting,
            "message": "Kinds still reroute to the governance alias; set them to another action first."})
    if old != alias:
        table = WorkspaceContentGovernance
        unchanged = (table.workspace_id == workspace_id, table.governance_alias == old)
        if row is None:
            await _apply(db, _insert(db, table(workspace_id=workspace_id, governance_alias=alias,
                                               updated_by=user_id, updated_at=utc_now())))
        elif alias is None:
            await _apply(db, db.execute(delete(table).where(*unchanged)))
        else:
            await _apply(db, db.execute(update(table).where(*unchanged).values(
                governance_alias=alias, updated_by=user_id, updated_at=utc_now())))
        _audit(db, user_id, workspace_id, GOVERNANCE_ALIAS, old, alias)
        await db.flush()
    return {"workspace_id": workspace_id, "governance_alias": alias}


__all__ = ["AUDIT_ACTION", "CODE_CONFLICT", "governance_aliases", "governance_row", "handling_view",
           "set_governance_alias", "set_handling", "stored_row"]
