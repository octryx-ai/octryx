"""Agent gateway: the user's own daily budget and seat allowance, for the launcher's status block.

Transport only; the read lives in ``services/agent_gateway/usage_read.py``.

- ``GET /api/v1/agent-gateway/daily-budget?workspace_id=`` — the launcher's login (gateway token, no session); the
  Workspace must be one of the user's, inside the grant's binding (else 403 ``workspace_not_authorized``).
  ``{state, reason, workspace_id, limit_usd, spent_usd, resets_at, seat_allowance, codex_seat_allowance}``: ``state``
  is ``allowed``, ``denied`` (``gateway_daily_budget_exhausted``) or ``needs_configuration`` (no or an invalid policy
  budget; the amounts are then ``null``). ``seat_allowance`` is the user's own latest Claude seat 5h/7d utilization,
  ``codex_seat_allowance`` the Codex seat's (ChatGPT's primary/secondary windows), each or ``null``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE
from ...services.agent_gateway.identity import GatewayRefusal, authorize_login_workspace, resolve_gateway_login
from ...services.agent_gateway.usage_read import own_gateway_usage

router = APIRouter(tags=["agent-gateway"])


def _refusal(refusal: GatewayRefusal) -> JSONResponse:
    return JSONResponse(
        {"state": refusal.state, "reason": refusal.reason},
        status_code=refusal.http_status,
        headers={HEADER_GATEWAY_STATE: refusal.state, HEADER_GATEWAY_REASON: refusal.reason},
    )


@router.get("/daily-budget")
async def own_daily_budget(
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
    usage = await own_gateway_usage(db, user_id=str(user.id), workspace_id=authorized)
    return JSONResponse(usage, headers={"cache-control": "no-store"})


__all__ = ["router"]
