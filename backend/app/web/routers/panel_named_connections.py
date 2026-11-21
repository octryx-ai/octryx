"""Named connections of a connector, per Workspace and global: list, create, update, delete, test.

One API for every connector type (its descriptor, ``named_connections/descriptors/``); the descriptor list
tells the UI which connector cards carry named connections and what their forms hold.

Secrets are write-only: a request may carry a typed secret, a response never carries a secret or a ref.
"""

from functools import partial

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.admin.project.named_connection_service import delete_named, save_named, test_named
from app.services.admin.project.named_connection_view import list_descriptors, list_named
from app.services.connector_test_service import run_connector_connection_test
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()

_WORKSPACE = "/chat/api/panel/projects/{project_id}/connectors/{connector_name}/named-connections"
_GLOBAL = "/chat/api/panel/connectors/{connector_name}/named-connections"
_DESCRIPTORS = "/chat/api/panel/named-connection-descriptors"


async def _json_body(request: Request) -> dict:
    try:
        payload = await request.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _list(db, connector_name, project_id):
    return JSONResponse(await list_named(db, connector=connector_name, project_id=project_id))


async def _save(request, db, user, connector_name, project_id, connection_id=None):
    saved = await save_named(
        db, connector=connector_name, project_id=project_id, payload=await _json_body(request),
        actor_id=user.id, connection_id=connection_id,
    )
    return JSONResponse(saved, status_code=201 if connection_id is None else 200)


async def _delete(db, user, connector_name, project_id, connection_id):
    return JSONResponse(
        await delete_named(
            db, connector=connector_name, project_id=project_id, connection_id=connection_id, actor_id=user.id
        )
    )


async def _test(request, db, user, connector_name, project_id, connection_id):
    return JSONResponse(
        await test_named(
            db, connector=connector_name, project_id=project_id, connection_id=connection_id,
            payload=await _json_body(request),
            run_connection_test=partial(run_connector_connection_test, db=db, scope_check=True),
            actor_id=user.id,
        )
    )


@router.get(_DESCRIPTORS)
async def panel_list_named_connection_descriptors(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(list_descriptors())


@router.get(_WORKSPACE)
async def panel_list_workspace_named_connections(
    project_id: str, connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_admin_api(request, db)
    return await _list(db, connector_name, project_id)


@router.post(_WORKSPACE)
async def panel_create_workspace_named_connection(
    project_id: str, connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _save(request, db, user, connector_name, project_id)


@router.put(_WORKSPACE + "/{connection_id}")
async def panel_update_workspace_named_connection(
    project_id: str, connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _save(request, db, user, connector_name, project_id, connection_id)


@router.delete(_WORKSPACE + "/{connection_id}")
async def panel_delete_workspace_named_connection(
    project_id: str, connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _delete(db, user, connector_name, project_id, connection_id)


@router.post(_WORKSPACE + "/{connection_id}/test")
async def panel_test_workspace_named_connection(
    project_id: str, connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _test(request, db, user, connector_name, project_id, connection_id)


@router.get(_GLOBAL)
async def panel_list_global_named_connections(
    connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_admin_api(request, db)
    return await _list(db, connector_name, None)


@router.post(_GLOBAL)
async def panel_create_global_named_connection(
    connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _save(request, db, user, connector_name, None)


@router.put(_GLOBAL + "/{connection_id}")
async def panel_update_global_named_connection(
    connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _save(request, db, user, connector_name, None, connection_id)


@router.delete(_GLOBAL + "/{connection_id}")
async def panel_delete_global_named_connection(
    connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _delete(db, user, connector_name, None, connection_id)


@router.post(_GLOBAL + "/{connection_id}/test")
async def panel_test_global_named_connection(
    connector_name: str, connection_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return await _test(request, db, user, connector_name, None, connection_id)
