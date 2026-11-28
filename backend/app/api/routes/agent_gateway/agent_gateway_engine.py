"""Agent gateway: the caller's effective coding engine in a Workspace, for the launcher."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.agent_gateway.engine_policy import effective_engine
from ....services.agent_gateway.identity import GatewayRefusal, authorize_login_workspace, resolve_gateway_login
from .agent_gateway_budget import _refusal

router = APIRouter(tags=["agent-gateway"])


@router.get("/engine")
async def own_engine(
    request: Request,
    workspace_id: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _refusal(login)
    user, context = login
    authorized, refusal = await authorize_login_workspace(db, user, context, workspace_id)
    if refusal is not None:
        return _refusal(refusal)
    setting = await effective_engine(db, user_id=str(user.id), workspace_id=authorized)
    return JSONResponse(setting.as_dict(), headers={"cache-control": "no-store"})


__all__ = ["router"]
