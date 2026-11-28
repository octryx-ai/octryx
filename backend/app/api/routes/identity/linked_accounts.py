"""Linked external accounts of a platform user."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User
from ....services.access_control import WORKSPACE_NOT_FOUND_MESSAGE, require_visible_workspace
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.auth import get_current_user
from ....services.linked_accounts.contract import ATLASSIAN, LinkedAccountError, platform
from ....services.linked_accounts.store import (
    account_row,
    account_rows,
    platform_catalog,
    remove_account,
    save_account,
    serialize_account,
)
from ....services.linked_accounts.verification import find_atlassian_account_by_email, verify_account

router = APIRouter(tags=["linked-accounts"])

_STATES = {400: "invalid", 403: "denied", 404: "not_found", 409: "needs_configuration"}


def _refusal(error: LinkedAccountError) -> JSONResponse:
    return JSONResponse({"state": _STATES.get(error.status, "invalid"), "reason": error.code,
                         "message": error.message}, status_code=error.status)


async def _target(db: AsyncSession, current_user: User, user_id: str) -> User:
    # The caller themself, or any user for a platform admin.
    target_id = current_user.id if user_id == "me" else user_id
    if target_id != current_user.id and not await is_global_admin(db, current_user.id):
        raise LinkedAccountError("not_your_account", "You can change only your own linked accounts.", 403)
    target = current_user if target_id == current_user.id else await db.get(User, target_id)
    if target is None:
        raise LinkedAccountError("unknown_user", "The user does not exist.", 404)
    return target


async def _named_workspace(db: AsyncSession, current_user: User, body: dict[str, Any] | None) -> str:
    # Resolved before anything is read or written: an unknown Workspace and one the caller is no member of are the same
    # project_not_found (platform admins: unknown only).
    project_id = str((body or {}).get("project_id") or "").strip()
    try:
        await require_visible_workspace(db, current_user.id, project_id or None)
    except HTTPException:
        raise LinkedAccountError("project_not_found", WORKSPACE_NOT_FOUND_MESSAGE, 404) from None
    return project_id


async def _workspaces(db: AsyncSession, current_user: User) -> list[dict[str, str]]:
    from ....services.project.private_workspace import outside_foreign_private
    from ....services.secure_work.access import work_scope_project_ids

    scope = await work_scope_project_ids(db, current_user)
    query = select(Project.id, Project.name).where(Project.is_active.is_(True)).order_by(Project.name).limit(200)
    if scope is None:
        query = query.where(outside_foreign_private(Project.id, current_user.id))
    else:
        if not scope:
            return []
        query = query.where(Project.id.in_(scope))
    return [{"id": row.id, "name": row.name} for row in (await db.execute(query)).all()]


async def _view(db: AsyncSession, current_user: User, target: User) -> dict[str, Any]:
    return {
        "user": {"id": target.id, "username": target.username, "display_name": target.display_name},
        "accounts": [serialize_account(row) for row in await account_rows(db, target.id)],
        "platforms": platform_catalog(),
        "workspaces": await _workspaces(db, current_user),
    }


@router.get("/api/v1/users/{user_id}/linked-accounts")
async def list_linked_accounts(user_id: str, current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    try:
        target = await _target(db, current_user, user_id)
    except LinkedAccountError as error:
        return _refusal(error)
    return JSONResponse(await _view(db, current_user, target))


@router.put("/api/v1/users/{user_id}/linked-accounts/{platform_key}")
async def save_linked_account(user_id: str, platform_key: str, body: dict[str, Any] = Body(...),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        target = await _target(db, current_user, user_id)
        project_id = await _named_workspace(db, current_user, body)
        spec = platform(platform_key)
        email = str(body.get("email") or "").strip()
        if email:
            if spec.key != ATLASSIAN:
                raise LinkedAccountError("email_lookup_unsupported", "Only an Atlassian account is found by email.")
            found = await find_atlassian_account_by_email(db, email=email, project_id=project_id, actor=current_user)
            row = await save_account(
                db, user_id=target.id, platform_key=spec.key, identifier=found["account_id"],
                display_name=found.get("display_name"), actor_id=current_user.id,
                verified={"status": "verified", "detail": "found by its email", "via": found["via"],
                          "project_id": project_id, "display_name": found.get("display_name")})
        else:
            row = await save_account(db, user_id=target.id, platform_key=spec.key,
                                     identifier=str(body.get("identifier") or ""),
                                     display_name=body.get("display_name"), actor_id=current_user.id)
    except LinkedAccountError as error:
        await db.rollback()
        return _refusal(error)
    await db.commit()
    await db.refresh(row)
    return JSONResponse({"state": "saved", "account": serialize_account(row)})


@router.post("/api/v1/users/{user_id}/linked-accounts/{platform_key}/verify")
async def verify_linked_account(user_id: str, platform_key: str, body: dict[str, Any] = Body(default={}),
                                current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        target = await _target(db, current_user, user_id)
        project_id = await _named_workspace(db, current_user, body)
        row = await account_row(db, target.id, platform(platform_key).key)
        if row is None:
            raise LinkedAccountError("not_linked", "Link the account before checking it.", 404)
        result = await verify_account(db, row, project_id=project_id, actor=current_user)
    except LinkedAccountError as error:
        await db.rollback()
        return _refusal(error)
    await db.commit()
    await db.refresh(row)
    return JSONResponse({"state": result["status"], "account": serialize_account(row)})


@router.delete("/api/v1/users/{user_id}/linked-accounts/{platform_key}")
async def remove_linked_account(user_id: str, platform_key: str, current_user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    try:
        target = await _target(db, current_user, user_id)
        removed = await remove_account(db, user_id=target.id, platform_key=platform_key, actor_id=current_user.id)
    except LinkedAccountError as error:
        return _refusal(error)
    await db.commit()
    return JSONResponse({"state": "removed" if removed else "not_linked"})
