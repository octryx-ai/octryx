"""Serializers for approvals: the approval in words, who decided it and a short summary of its change preview."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, User
from ...services.approval.presentation import approval_texts
from ...services.standing_approvals.argument_class import standing_rule_view
from .serialization import _serialize_timestamp

__all__ = ["approver_names", "_summarize_change_preview", "_serialize_approval"]


def _summarize_change_preview(preview: dict | None) -> str:
    if not isinstance(preview, dict):
        return ""
    preview_payload = preview.get("preview")
    if isinstance(preview_payload, dict):
        if isinstance(preview_payload.get("summary"), str) and preview_payload.get("summary"):
            return str(preview_payload["summary"])
        if isinstance(preview_payload.get("command"), str) and preview_payload.get("command"):
            return str(preview_payload["command"])
        if isinstance(preview_payload.get("path"), str) and preview_payload.get("path"):
            return str(preview_payload["path"])
    tool_name = str(preview.get("toolName") or "").strip()
    request_fingerprint = str(preview.get("requestFingerprint") or "").strip()
    return tool_name or request_fingerprint


async def approver_names(db: AsyncSession, approvals: list[Approval]) -> dict[str, str]:
    ids = {str(approval.approved_by) for approval in approvals if approval.approved_by}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids)))).all()
    return {str(row.id): str(row.display_name or row.username or "") for row in rows}


def _serialize_approval(
    approval: Approval, *, change_preview: dict | None = None,
    approver_name_by_id: dict[str, str] | None = None,
) -> dict:
    # ``title``/``subtitle``/``details``: the approval in words, as the approval page and the phone show it
    # (``approval/presentation``); the preview keeps its machine fields.
    preview = change_preview.get("preview") if isinstance(change_preview, dict) else None
    return {
        **approval_texts(preview if isinstance(preview, dict) else None, approval.action or ""),
        "id": approval.id,
        "taskRunId": approval.task_run_id or "",
        "sessionId": approval.session_id or "",
        "requestedBy": approval.requested_by,
        "approvedBy": approval.approved_by or "",
        "approvedByName": (approver_name_by_id or {}).get(str(approval.approved_by or "")) or "",
        "action": approval.action or "",
        "status": approval.status or "",
        "reason": approval.reason or "",
        "decisionNote": approval.decision_note or "",
        "createdAt": _serialize_timestamp(approval.created_at),
        "resolvedAt": _serialize_timestamp(approval.resolved_at),
        "changePreview": change_preview,
        # The scope "Always for this Workspace" would grant; null when it is not offered.
        "standingRule": standing_rule_view(change_preview),
    }
