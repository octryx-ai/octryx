"""Connector pause/resume, usage and guarded removal (automation V2)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.admin.connector.connector_lifecycle import (
    connector_usage,
    set_connector_active,
)
from .._helpers.api_guards import _require_admin_api

router = APIRouter()


class ConnectorActiveRequest(BaseModel):
    is_active: bool


@router.get("/chat/api/panel/connectors/{tool_name}/usage")
async def panel_connector_usage(tool_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await connector_usage(db, tool_name))


@router.post("/chat/api/panel/connectors/{tool_name}/active")
async def panel_connector_active(
    tool_name: str, payload: ConnectorActiveRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await set_connector_active(db, tool_name=tool_name, is_active=payload.is_active, actor_user_id=user.id)
    )
