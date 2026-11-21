"""Admin panel: the private-host allowlist for on-prem connections.

Admin-only. ``GET`` lists every allowlistable connection type with its ``host:port`` entries;
``PUT`` replaces the entries of one type after validation and records the audit row
``egress.private_hosts.updated`` (``services/outbound_egress/private_hosts.py``). A refused
entry answers 400 with ``state = private_host_entry_refused``, a fixed ``reason`` and the
index of the refused entry; nothing is stored.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.outbound_egress import ALLOWLISTABLE_CONNECTIONS
from app.services.outbound_egress.private_hosts import (
    PrivateHostAllowlistError,
    read_private_host_allowlist,
    replace_private_host_entries,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/egress/private-hosts")
async def panel_get_private_hosts(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    try:
        connections = await read_private_host_allowlist(db)
    except PrivateHostAllowlistError as refused:
        return JSONResponse(status_code=409, content={"detail": {"state": refused.reason}})
    return JSONResponse({"allowlistable": list(ALLOWLISTABLE_CONNECTIONS), "connections": connections})


@router.put("/chat/api/panel/egress/private-hosts/{connection}")
async def panel_put_private_hosts(
    connection: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    try:
        entries = await replace_private_host_entries(
            db, connection=connection, entries=payload.get("entries"), actor_user_id=admin.id
        )
    except PrivateHostAllowlistError as refused:
        await db.rollback()
        return JSONResponse(status_code=400, content={"detail": refused.detail()})
    await db.commit()
    return JSONResponse({"connection": connection, "entries": entries})
