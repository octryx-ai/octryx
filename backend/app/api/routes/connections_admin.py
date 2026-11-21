"""The admin connections API. Transport only; the service is ``services/connections``.

- ``GET  /api/v1/admin/connection-types`` — ``[{type, label, auth_kinds, access_fields, uses, scope_key, …}]``
- ``GET  /api/v1/admin/connections?type=&state=&workspace_id=`` — ``{connections: [...]}``
- ``POST /api/v1/admin/connections`` — create; ``201`` with the detail
- ``GET|PUT|DELETE /api/v1/admin/connections/{id}`` — detail; partial update → detail; delete or ``409``
- ``POST /api/v1/admin/connections/{id}/test`` — ``{state, state_reason, tested_at, checks}``

Platform admins see and change everything; Workspace admins see what is available in or owned by their Workspaces
and change only their own (``rights.py``), but may test every connection they see (the test only reads from the
provider); anyone else gets 403. Responses never carry a secret.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.connections import store
from ...services.connections.catalog import list_connection_types
from ...services.connections.contract import CODE_PLATFORM_ADMIN_REQUIRED, not_found, refusal
from ...services.connections.deletion import delete_connection
from ...services.connections.rights import Viewer, admin_viewer
from ...services.connections.testing import test_connection
from ...services.connections.uses_write import apply_uses, parse_uses
from ...services.connections.views import detail_view, list_view
from ...services.connections.writes import save_connection
from ...services.connector_test_service import run_connector_connection_test

router = APIRouter(prefix="/api/v1/admin", tags=["connections"])


async def _visible(db: AsyncSession, viewer: Viewer, connection_id: str, *, edit: bool = False):
    row = await store.get_row(db, connection_id)
    if row is None:
        raise not_found()
    ws = (await store.workspaces_of(db, [row.id]))[row.id]
    if not viewer.can_see(row, ws):
        raise not_found()
    if edit and not viewer.can_edit(row, ws):
        raise refusal(403, CODE_PLATFORM_ADMIN_REQUIRED, "This connection is managed by platform admins.")
    return row


async def _save(db: AsyncSession, viewer: Viewer, user: User, body: dict[str, Any], row=None):
    body = body if isinstance(body, dict) else {}
    parsed = parse_uses(row, body["uses"]) if row is not None and "uses" in body else None
    try:
        saved = await save_connection(db, viewer, body, row)
        if row is None and "uses" in body:
            parsed = parse_uses(saved, body["uses"])
        if parsed:
            await apply_uses(db, user, saved, parsed)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(saved)
    return saved


@router.get("/connection-types")
async def get_connection_types(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await admin_viewer(db, user)
    return list_connection_types()


@router.get("/connections")
async def get_connections(type: str | None = None, state: str | None = None, workspace_id: str | None = None,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    return await list_view(db, viewer, connection_type=type, state=state, workspace_id=workspace_id)


@router.post("/connections")
async def post_connection(body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    saved = await _save(db, viewer, user, body)
    return JSONResponse(await detail_view(db, viewer, saved), status_code=201)


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: str, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    return await detail_view(db, viewer, await _visible(db, viewer, connection_id))


@router.put("/connections/{connection_id}")
async def put_connection(connection_id: str, body: dict[str, Any] = Body(...),
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    row = await _visible(db, viewer, connection_id, edit=True)
    saved = await _save(db, viewer, user, body, row)
    return await detail_view(db, viewer, saved)


@router.delete("/connections/{connection_id}")
async def remove_connection(connection_id: str, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    row = await _visible(db, viewer, connection_id, edit=True)
    result = await delete_connection(db, row, actor_id=user.id)
    await db.commit()
    return result


@router.post("/connections/{connection_id}/test")
async def post_connection_test(connection_id: str, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    viewer = await admin_viewer(db, user)
    # Read-only towards the provider: any admin who sees the connection may test it (it keeps state).
    row = await _visible(db, viewer, connection_id)
    result = await test_connection(db, row, actor_id=user.id,
                                   run_test=partial(run_connector_connection_test, db=db, scope_check=True))
    await db.commit()
    return result


__all__ = ["router"]
