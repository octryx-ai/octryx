"""A Workspace's connections and its deviations. Transport only.

- ``GET    /api/v1/workspaces/{ws}/connections`` — ``{connections: [{id, name, type, state, effective, deviation,
  base, can_edit}]}`` for members of the Workspace; ``base`` is the widest the Workspace may use
- ``PUT    /api/v1/workspaces/{ws}/connections/{id}/deviation`` — ``{effective, deviation, base}``; narrower only
  (``422 deviation_not_narrower`` with ``field``)
- ``DELETE /api/v1/workspaces/{ws}/connections/{id}/deviation`` — ``{effective, deviation: null}``

An unknown Workspace and one the caller is no member of are the same 404 ``project_not_found``. Setting and
resetting are for the Workspace's admins and platform admins; any other member gets 403.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user
from ...services.connections.deviations import reset_deviation, set_deviation, workspace_list
from ...services.connections.rights import require_workspace_admin, workspace_viewer

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspace-connections"])


@router.get("/{workspace_id}/connections")
async def get_workspace_connections(workspace_id: str, user: User = Depends(get_current_user),
                                    db: AsyncSession = Depends(get_db)):
    await require_visible_workspace(db, user.id, workspace_id)
    viewer, _role = await workspace_viewer(db, user, workspace_id)
    return await workspace_list(db, viewer, workspace_id)


@router.put("/{workspace_id}/connections/{connection_id}/deviation")
async def put_connection_deviation(workspace_id: str, connection_id: str, body: Any = Body(...),
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_visible_workspace(db, user.id, workspace_id)
    viewer, _role = await workspace_viewer(db, user, workspace_id)
    require_workspace_admin(viewer, workspace_id)
    result = await set_deviation(db, viewer, workspace_id, connection_id, body)
    await db.commit()
    return result


@router.delete("/{workspace_id}/connections/{connection_id}/deviation")
async def delete_connection_deviation(workspace_id: str, connection_id: str, user: User = Depends(get_current_user),
                                      db: AsyncSession = Depends(get_db)):
    await require_visible_workspace(db, user.id, workspace_id)
    viewer, _role = await workspace_viewer(db, user, workspace_id)
    require_workspace_admin(viewer, workspace_id)
    result = await reset_deviation(db, viewer, workspace_id, connection_id)
    await db.commit()
    return result


__all__ = ["router"]
