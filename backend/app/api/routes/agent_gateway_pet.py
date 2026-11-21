"""Agent gateway: the Octryx pet's state (``octryx-claude pet``, the tray icon).

Transport only; the view lives in ``services/attention/pet_view.py`` over ``services/attention/service.py``.

- ``GET /api/v1/agent-gateway/pet?project_id=`` — the launcher's login (gateway token, no session). Without
  ``project_id`` the view covers the user's whole queue, limited to the grant's binding when the login is bound; with
  it, the Workspace must be one of the user's inside the binding (else 403 ``workspace_not_authorized``).
- The answer carries an ``ETag``; ``If-None-Match`` with the current one is answered 304 without a body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE
from ...services.agent_gateway.identity import GatewayRefusal, authorize_login_workspace, resolve_gateway_login
from ...services.attention.pet_view import pet_view, view_etag
from ...services.attention.service import attention

router = APIRouter(tags=["agent-gateway"])


def _refusal(refusal: GatewayRefusal) -> JSONResponse:
    return JSONResponse(
        {"state": refusal.state, "reason": refusal.reason},
        status_code=refusal.http_status,
        headers={HEADER_GATEWAY_STATE: refusal.state, HEADER_GATEWAY_REASON: refusal.reason},
    )


@router.get("/pet")
async def pet_state(
    request: Request,
    project_id: str | None = Query(default=None, min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _refusal(login)
    user, context = login
    workspaces = None if context.bound_project_ids is None else set(context.bound_project_ids)
    if project_id is not None:
        authorized, refusal = await authorize_login_workspace(db, user, context, project_id)
        if refusal is not None:
            return _refusal(refusal)
        workspaces = {authorized}
    view = pet_view(await attention(db, user), workspaces=workspaces)
    etag = view_etag(view)
    headers = {"etag": etag, "cache-control": "no-cache"}
    if etag in [part.strip() for part in str(request.headers.get("if-none-match") or "").split(",")]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(view, headers=headers)


__all__ = ["router"]
