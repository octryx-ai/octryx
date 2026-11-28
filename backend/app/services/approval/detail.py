"""One approval as the detail page, the phone list and the attention queue show it (``GET /api/v1/approvals/...``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User
from .presentation import approval_texts


async def latest_preview_payload(db: AsyncSession, approval_id: str) -> dict[str, Any] | None:
    from ...models import ChangePreview
    from ..change_preview.service import serialize_change_preview

    preview = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == approval_id)
                                .order_by(ChangePreview.created_at.desc()).limit(1))).scalar_one_or_none()
    serialized = serialize_change_preview(preview)
    payload = (serialized or {}).get("preview") if serialized else None
    return payload if isinstance(payload, dict) else None


async def approval_detail(db: AsyncSession, approval: Approval) -> dict[str, Any]:
    from ...models import WorkflowRunSession
    from ..change_preview.service import offered_decisions

    payload = await latest_preview_payload(db, approval.id)
    names = {}
    for user_id in {approval.requested_by, approval.approved_by} - {None}:
        user = await db.get(User, user_id)
        names[user_id] = (user.display_name or user.username) if user is not None else None
    run_id = None
    if approval.session_id:
        run_id = (await db.execute(select(WorkflowRunSession.run_id).where(
            WorkflowRunSession.session_id == approval.session_id).limit(1))).scalar_one_or_none()
    return {
        **approval_texts(payload, approval.action or ""),
        "payload": payload,
        "offered_decisions": offered_decisions(payload) if payload is not None else ["once", "deny"],
        "decision_note": approval.decision_note,
        "requested_by_name": names.get(approval.requested_by),
        "approved_by_name": names.get(approval.approved_by),
        "workspace_id": approval.workspace_id,
        "workflow_run_id": run_id,
    }


__all__ = ["approval_detail", "latest_preview_payload"]
