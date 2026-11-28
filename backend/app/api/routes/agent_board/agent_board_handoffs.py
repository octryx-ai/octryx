"""Handoffs and takeovers REST for the UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_board.takeover_listing import takeover_views

from ....db import get_db
from ....models import (
    AuditLog,
    User,
    WorkItem,
    WorkItemClaim,
    WorkItemHandoff,
    WorkItemHandoffAttachment,
    WorkItemTakeover,
)
from ....services.agent_board.client_handoff import request_hand_over_now
from ....services.agent_board.handoff_attachments import load_bundle
from ....services.agent_board.handoffs import handoff_views, latest_handoff, list_handoffs
from ....services.agent_board.takeover_effects import after_takeover_decision
from ....services.agent_board.takeovers import decide_takeover, list_takeovers
from ....services.auth import get_current_user
from .agent_board_access import interactive_user, require_member, viewer

router = APIRouter()
HAND_OVER_NOW_AUDIT_ACTION = "agent_board.claim.hand_over_now"


@router.get("/handoffs")
async def get_handoffs(
    project_id: str = Query(..., min_length=1, max_length=64),
    work_item_id: str | None = Query(None, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = await require_member(db, current_user.id, project_id)
    if work_item_id:
        item = await db.get(WorkItem, work_item_id)
        if item is None or item.project_id != project_id:
            raise HTTPException(status_code=404, detail="Work item not found")
    rows = await list_handoffs(db, project_id=project_id, work_item_id=work_item_id)
    return {"items": await handoff_views(db, rows), "viewer": viewer(current_user.id, role)}


@router.get("/handoffs/{handoff_id}")
async def get_handoff(
    handoff_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    handoff = await db.get(WorkItemHandoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    role = await require_member(db, current_user.id, handoff.project_id, not_found="Handoff not found")
    [view] = await handoff_views(db, [handoff])
    return {**view, "viewer": viewer(current_user.id, role)}


@router.get("/takeovers")
async def get_takeovers(
    project_id: str = Query(..., min_length=1, max_length=64),
    status: str | None = Query(None, max_length=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = await require_member(db, current_user.id, project_id)
    rows = await list_takeovers(db, project_id=project_id, status=status or None)
    items = [{key: value for key, value in view.items() if key != "project_id"} for view in
             await takeover_views(db, rows)]
    await db.commit()  # expired pending takeovers are stored as expired
    return {"items": items, "viewer": viewer(current_user.id, role)}


async def _decide(db: AsyncSession, takeover_id: str, user: User, *, confirm: bool) -> dict[str, Any]:
    takeover = await db.get(WorkItemTakeover, takeover_id)
    if takeover is None:
        raise HTTPException(status_code=404, detail="Takeover not found")
    role = await require_member(db, user.id, takeover.project_id, not_found="Takeover not found")
    try:
        takeover = await decide_takeover(db, takeover=takeover, user_id=user.id, confirm=confirm)
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get("code") == "takeover_not_pending":
            await db.commit()  # an expired or no longer applicable takeover is stored as such
        raise
    await after_takeover_decision(db, takeover, actor_user_id=user.id)
    [view] = await takeover_views(db, [takeover])
    handoff = await latest_handoff(db, takeover.work_item_id) if confirm else None
    rendered = (await handoff_views(db, [handoff]))[0] if handoff is not None else None
    await db.commit()
    return {"takeover": view, "handoff": rendered, "viewer": viewer(user.id, role)}


@router.post("/takeovers/{takeover_id}/confirm")
async def confirm_takeover(
    takeover_id: str, current_user: User = Depends(interactive_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _decide(db, takeover_id, current_user, confirm=True)


@router.post("/takeovers/{takeover_id}/decline")
async def decline_takeover(
    takeover_id: str, current_user: User = Depends(interactive_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _decide(db, takeover_id, current_user, confirm=False)


@router.get("/handoff-attachments/{attachment_id}")
async def download_handoff_attachment(
    attachment_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    """A handoff's git bundle for the Workspace's members (audited)."""
    attachment = await db.get(WorkItemHandoffAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await require_member(db, current_user.id, attachment.project_id, not_found="Attachment not found")
    data = await load_bundle(db, attachment=attachment, user_id=current_user.id)
    await db.commit()
    return Response(content=data, media_type="application/octet-stream", headers={
        "content-disposition": f'attachment; filename="handoff-{attachment.id}.bundle"',
        "x-octryx-sha256": attachment.sha256, "cache-control": "no-store"})


@router.post("/claims/{claim_id}/hand-over-now")
async def hand_over_now(
    claim_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """The "Hand over now" action (Workspace admin/owner, platform admin): the claim's handoff request now; the
    holder's client runs the git step on its next hook call (``handoff_now``)."""
    claim = await db.get(WorkItemClaim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    role = await require_member(db, current_user.id, claim.project_id, admin=True, not_found="Claim not found")
    if claim.released_at is not None:
        raise HTTPException(status_code=409, detail={"code": "claim_released"})
    session_asked = await request_hand_over_now(db, claim)
    db.add(AuditLog(user_id=current_user.id, action=HAND_OVER_NOW_AUDIT_ACTION, resource_type="work_item_claim",
                    resource_id=claim.id, project_id=claim.project_id,
                    details={"project_id": claim.project_id, "session_asked": session_asked}))
    await db.commit()
    return {"claim_id": claim.id, "requested": True, "session_asked": session_asked,
            "viewer": viewer(current_user.id, role)}


__all__ = ["router"]
