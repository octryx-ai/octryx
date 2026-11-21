"""A Workspace's sensitive-content handling (``content_security.handling``). Transport only.

- ``GET /api/v1/workspaces/{ws}/content-handling`` — the Workspace's governance alias (``governance_alias``) and the
  governed aliases it may name (``governance_aliases``); per kind the effective action, its default, where a reroute
  is unavailable, what the action does at each enforcement point (``surface_defaults``) and what each choice would do
  there (``surface_choices``); the actions and the fixed rules (any member; ``can_edit`` for the Workspace's
  admins/owners and platform admins);
- ``PUT /api/v1/workspaces/{ws}/content-handling/governance-alias`` — ``{"alias": <alias>|null}``: the one governed
  alias every ``reroute`` / ``mask_reroute`` kind is sent to; ``{"workspace_id", "governance_alias"}``; 422
  ``content_handling_alias_unknown`` for an alias that is not an active governed alias, 409
  ``content_handling_alias_in_use`` (with ``kinds``) for clearing it while kinds reroute;
- ``PUT /api/v1/workspaces/{ws}/content-handling/{kind}`` — ``{"action": <action>|"default"}``; the updated kind
  entry; 422 with ``detail.code`` for an unknown kind, an invalid action, and a reroute action while the Workspace
  has no governance alias (``content_handling_alias_required``).

Both edits return 409 ``content_handling_conflict`` when a concurrent edit won (nothing is changed); every change is
audited (``content_handling.changed``, ``kind``: the content kind or ``governance_alias``) with the real old→new
transition.

An unknown Workspace and one the caller is no member of are the same 404 ``project_not_found``; a member without
the admin/owner role gets 403 on ``PUT``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import get_project_role_for_user, require_project_access
from ...services.auth import get_current_user
from ...services.content_security.handling_settings import handling_view, set_governance_alias, set_handling

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspace-content-handling"])
EDIT_ROLES = frozenset({"admin", "owner"})


@router.get("/{workspace_id}/content-handling")
async def get_content_handling(workspace_id: str, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id)
    role = await get_project_role_for_user(db, user.id, workspace_id)
    return await handling_view(db, workspace_id, can_edit=role in EDIT_ROLES)


@router.put("/{workspace_id}/content-handling/governance-alias")
async def put_governance_alias(workspace_id: str, body: Any = Body(...), user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id, require_admin=True)
    view = await set_governance_alias(db, workspace_id, body, user_id=user.id)
    await db.commit()
    return view


@router.put("/{workspace_id}/content-handling/{kind}")
async def put_content_handling(workspace_id: str, kind: str, body: Any = Body(...),
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_project_access(db, user.id, workspace_id, require_admin=True)
    entry = await set_handling(db, workspace_id, kind, body, user_id=user.id)
    await db.commit()
    return entry


__all__ = ["router"]
