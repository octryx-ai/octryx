"""Agent coordination board REST for the UI. Transport only; rules live in ``services/agent_board``.

- ``GET /api/v1/agent-board/claims?project_id=`` — live work-item claims of a Workspace (members).
- ``POST /api/v1/agent-board/claims/{id}/release`` — Workspace admin/owner or platform admin; the claim ends
  ``admin_released`` and an audit row records it.
- The message board routes (``agent_board_messages.py``) are mounted here as well.

A caller who is not a member of the Workspace gets 404, exactly like a missing Workspace or claim.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_board.claim_listing import list_live_claims

from ...db import get_db
from ...models import User, WorkItemClaim
from ...services.agent_board.claims import admin_release_claim
from ...services.auth import get_current_user
from . import agent_board_handoffs, agent_board_messages, agent_board_test_hooks
from .agent_board_access import require_member, viewer

router = APIRouter(prefix="/api/v1/agent-board", tags=["agent-board"])
# The message board, decisions, handoff requests and action-needed share this mount.
router.include_router(agent_board_messages.router)
# Handoffs and takeovers as well.
router.include_router(agent_board_handoffs.router)
# The env-gated live-acceptance hook (404 unless OCTRYX_ENABLE_TEST_HOOKS=true).
router.include_router(agent_board_test_hooks.router)


@router.get("/claims")
async def list_claims(
    project_id: str = Query(..., min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = await require_member(db, current_user.id, project_id)
    items = await list_live_claims(db, [project_id])
    return {
        "items": [{key: value for key, value in item.items() if key != "project_id"} for item in items],
        "viewer": viewer(current_user.id, role),
    }


@router.post("/claims/{claim_id}/release")
async def release_claim(
    claim_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    claim = await db.get(WorkItemClaim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    await require_member(db, current_user.id, claim.project_id, admin=True, not_found="Claim not found")
    answer = await admin_release_claim(db, claim=claim, actor_user_id=current_user.id)
    await db.commit()
    return answer


__all__ = ["router"]
