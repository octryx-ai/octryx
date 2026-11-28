"""Admin API of the custom REST connector; platform admins only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.rest_connector import connections, definitions
from .._helpers.api_guards import _require_admin_api

router = APIRouter()
BASE = "/chat/api/panel/rest-apis"


@router.get(BASE)
async def panel_list_rest_apis(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.list_definitions(db))


@router.post(BASE)
async def panel_create_rest_api(request: Request, payload: dict[str, Any] = Body(...),
                                db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await definitions.create_definition(db, payload, actor_user_id=user.id))


@router.post(f"{BASE}/import")
async def panel_import_rest_api(request: Request, payload: dict[str, Any] = Body(...),
                                db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await definitions.import_definition(db, payload, actor_user_id=user.id))


@router.get(f"{BASE}/{{definition_id}}")
async def panel_get_rest_api(definition_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.get_definition(db, definition_id))


@router.put(f"{BASE}/{{definition_id}}")
async def panel_update_rest_api(definition_id: str, request: Request, payload: dict[str, Any] = Body(...),
                                db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.update_definition(db, definition_id, payload))


@router.delete(f"{BASE}/{{definition_id}}")
async def panel_delete_rest_api(definition_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.delete_definition(db, definition_id))


@router.post(f"{BASE}/{{definition_id}}/operations")
async def panel_add_rest_operation(definition_id: str, request: Request, payload: dict[str, Any] = Body(...),
                                   db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.add_operation(db, definition_id, payload))


@router.put(f"{BASE}/{{definition_id}}/operations/{{operation_id}}")
async def panel_update_rest_operation(definition_id: str, operation_id: str, request: Request,
                                      payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.update_operation(db, definition_id, operation_id, payload))


@router.delete(f"{BASE}/{{definition_id}}/operations/{{operation_id}}")
async def panel_delete_rest_operation(definition_id: str, operation_id: str, request: Request,
                                      db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.delete_operation(db, definition_id, operation_id))


@router.post(f"{BASE}/{{definition_id}}/operations/{{operation_id}}/test")
async def panel_test_rest_operation(definition_id: str, operation_id: str, request: Request,
                                    payload: dict[str, Any] = Body(default_factory=dict),
                                    db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await definitions.admin_test_call(db, definition_id, operation_id, payload,
                                                          admin_user_id=user.id))


@router.get(f"{BASE}/{{definition_id}}/connections")
async def panel_list_rest_connections(definition_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await connections.list_connections(db, definition_id))


@router.post(f"{BASE}/{{definition_id}}/connections")
async def panel_create_rest_connection(definition_id: str, request: Request, payload: dict[str, Any] = Body(...),
                                       db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await connections.create_connection(db, definition_id, payload))


@router.put(f"{BASE}/{{definition_id}}/connections/{{connection_id}}")
async def panel_update_rest_connection(definition_id: str, connection_id: str, request: Request,
                                       payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await connections.update_connection(db, definition_id, connection_id, payload))


@router.delete(f"{BASE}/{{definition_id}}/connections/{{connection_id}}")
async def panel_delete_rest_connection(definition_id: str, connection_id: str, request: Request,
                                       db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await connections.delete_connection(db, definition_id, connection_id))


@router.get("/chat/api/panel/rest-api-calls")
async def panel_recent_rest_calls(request: Request, limit: int = 50, definition_id: str | None = None,
                                  op_id: str | None = None, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await definitions.recent_calls(db, limit=limit, definition_id=definition_id or None,
                                                       operation_id=op_id or None))
