"""Workspace authorization of a registry API (read = any role, author = admin or owner).

Same semantics as ``services/agent_definition_access`` and the knowledge
Workspace authorization:

* a Workspace that does not exist and a Workspace the caller has no role in are
  answered with the same 404, so the API never confirms another Workspace's ids;
  the project row is checked *before* the role, because a global admin resolves
  to ``admin`` for any id;
* reading needs any role in the Workspace; authoring, submitting, publishing,
  retiring and importing need the ``admin`` or ``owner`` role (403 otherwise,
  which discloses nothing the caller could not already read).

Approving is not authorized here: it happens through the approvals API, and the
four-eyes rule is enforced at publish time.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, User
from .access_control import get_project_role_for_user

WORKSPACE_NOT_FOUND_DETAIL = "Workspace not found"
AUTHOR_ROLE_REQUIRED_DETAIL = "Project admin or owner role required for this action."
AUTHOR_PROJECT_ROLES = frozenset({"admin", "owner"})


async def authorize_workspace(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    require_author: bool,
    not_found_detail: Any = WORKSPACE_NOT_FOUND_DETAIL,
) -> str:
    """Return the canonical Workspace id, or raise 404 / 403.

    ``not_found_detail`` lets a row lookup (a policy) answer an
    out-of-scope row with exactly the body of an unknown one.
    """
    project_id = str(workspace_id or "").strip()
    exists = (
        (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
        if project_id
        else None
    )
    if exists is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    role = await get_project_role_for_user(db, current_user.id, project_id)
    if role is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    if require_author and role not in AUTHOR_PROJECT_ROLES:
        raise HTTPException(status_code=403, detail=AUTHOR_ROLE_REQUIRED_DETAIL)
    return project_id


__all__ = ["AUTHOR_PROJECT_ROLES", "authorize_workspace"]
