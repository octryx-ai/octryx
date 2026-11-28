"""Auto-extracted router module: chat_approvals."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory, get_db
from app.schemas.admin.admin_panel._governance import BudgetPolicyUpsertRequest
from app.services.admin.provider.admin_circuit_breaker_service import admin_list_circuit_breakers
from app.services.budget import (
    list_budget_alert_surface as admin_list_budget_alert_surface,
)
from app.services.budget import (
    list_budget_policies as admin_list_budget_policies,
)
from app.services.budget import (
    upsert_budget_policy as admin_upsert_budget_policy,
)
from app.services.session.approval_decision import decide_session_approval
from app.services.standing_approvals.decision import decide_approval_always
from app.web._helpers._chat_state_builder import _build_chat_state
from app.web._helpers._serialization_ext import _serialize_budget_policy
from app.web._helpers.api_guards import _require_admin_api, _require_api_user

from ...services.access_control import require_existing_workspace
from .panel_identity_exec_policies import router as panel_identity_exec_policies_router

router = APIRouter()


async def _decide_from_chat(request: Request, db: AsyncSession, *, approval_id: str, decision: str, reason: str):
    user = await _require_api_user(request, db)
    approval = await decide_session_approval(
        db,
        approval_id=approval_id,
        decider_id=user.id,
        decision=decision,
        reason=reason,
        session_factory=getattr(request.app.state, "async_session_factory", async_session_factory),
    )
    return JSONResponse(await _build_chat_state(request, db, user=user, session_id=approval.session_id))


@router.post("/chat/api/approvals/{approval_id}/approve")
async def chat_approve_approval_api(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _decide_from_chat(
        request, db, approval_id=approval_id, decision="approved", reason="Approved in chat"
    )


@router.post("/chat/api/approvals/{approval_id}/reject")
async def chat_reject_approval_api(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await _decide_from_chat(
        request, db, approval_id=approval_id, decision="rejected", reason="Rejected in chat"
    )


@router.post("/chat/api/approvals/{approval_id}/always")
async def chat_always_approval_api(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Always for this Workspace: record the standing rule (Workspace admin/owner), then approve."""
    user = await _require_api_user(request, db)
    approval = await decide_approval_always(
        db,
        approval_id=approval_id,
        decider_id=user.id,
        session_factory=getattr(request.app.state, "async_session_factory", async_session_factory),
    )
    return JSONResponse(await _build_chat_state(request, db, user=user, session_id=approval.session_id))


@router.get("/budget-policies")
async def admin_list_budget_policies_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_budget_policies(db, serialize_policy=_serialize_budget_policy))


@router.post("/budget-policies")
async def admin_upsert_budget_policy_route(
    payload: BudgetPolicyUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await admin_upsert_budget_policy(
            db,
            payload=payload.model_dump(exclude_none=True),
            serialize_policy=_serialize_budget_policy,
            actor_user_id=admin.id,
        )
    )


@router.get("/chat/api/panel/budget-policies")
async def admin_panel_list_budget_policies(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_budget_policies(db, serialize_policy=_serialize_budget_policy))


@router.get("/chat/api/panel/budget-alerts")
async def admin_panel_list_budget_alerts(
    request: Request,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_budget_alert_surface(db, limit=limit))


@router.post("/chat/api/panel/budget-policies")
async def admin_panel_upsert_budget_policy(
    payload: BudgetPolicyUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(
        await admin_upsert_budget_policy(
            db,
            payload=payload.model_dump(exclude_none=True),
            serialize_policy=_serialize_budget_policy,
            actor_user_id=admin.id,
        )
    )


@router.get("/circuit-breakers")
async def admin_list_circuit_breakers_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_circuit_breakers(db))


@router.get("/chat/api/panel/circuit-breakers")
async def admin_panel_list_circuit_breakers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_circuit_breakers(db))


router.include_router(panel_identity_exec_policies_router)
