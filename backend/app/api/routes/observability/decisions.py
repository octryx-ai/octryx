"""Observability → Decisions (O2): the timeline, one decision with its approval lifecycle, today's counts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth.admin_principal import get_current_admin_user
from ....services.decisions.timeline import (
    DEFAULT_WINDOW_HOURS,
    decisions_today,
    get_decision,
    list_decisions,
    policy_denial_counts,
)

router = APIRouter()


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.get("/decisions")
async def get_decisions(
    window_hours: int = Query(default=DEFAULT_WINDOW_HOURS, ge=1, le=720),
    outcome: str | None = Query(default=None, max_length=20),
    gate: str | None = Query(default=None, max_length=40),
    workspace_id: str | None = Query(default=None, max_length=64),
    policy_id: str | None = Query(default=None, max_length=200),
    run_key: str | None = Query(default=None, max_length=120),
    approval_id: str | None = Query(default=None, max_length=36),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_decisions(
        db, window_hours=window_hours, outcome=_clean(outcome), gate=_clean(gate), workspace_id=_clean(workspace_id),
        policy_id=_clean(policy_id), run_key=_clean(run_key), approval_id=_clean(approval_id), page=page,
        page_size=page_size,
    )


@router.get("/decisions/today")
async def get_decisions_today(_admin: User = Depends(get_current_admin_user), db: AsyncSession = Depends(get_db)):
    return await decisions_today(db)


@router.get("/decisions/policy-counts")
async def get_policy_counts(
    days: int = Query(default=7, ge=1, le=30),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return {"days": days, "denied": await policy_denial_counts(db, days=days)}


@router.get("/decisions/{decision_id}")
async def get_one_decision(
    decision_id: str,
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    payload = await get_decision(db, decision_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return payload
