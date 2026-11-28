"""Device job approvals: the owner's decision, expiry, and the device's request (``devices.jobs``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobApproval
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..decisions.devices import record_device_approval
from ..secret_masking import masked_text
from .job_state import (
    DECISION_ALLOW_JOB_EDITS,
    DECISIONS,
    EDIT_TOOLS,
    MAX_PREVIEW_CHARS,
    REASON_APPROVAL_DECIDED,
    REASON_APPROVAL_EXPIRED,
    REASON_APPROVAL_NOT_FOUND,
    REASON_DECISION_INVALID,
    REASON_JOB_EDITS_NOT_ALLOWED,
    REASON_NOT_OWNER,
    DeviceJobError,
    _audit,
    _clip,
    input_digest,
)


async def decide_approval(
    db: AsyncSession, *, job_id: str, approval_id: str, user_id: str, decision: Any,
) -> DeviceJobApproval:
    job = await db.get(DeviceJob, job_id) if job_id else None
    approval = await db.get(DeviceJobApproval, approval_id) if approval_id else None
    if job is None or approval is None or approval.job_id != job.id:
        raise DeviceJobError(REASON_APPROVAL_NOT_FOUND, 404)
    if job.owner_user_id != user_id or approval.owner_user_id != user_id:
        # The hard invariant: no admin, no delegate, no Workspace approver answers a device's approval.
        raise DeviceJobError(REASON_NOT_OWNER, 403)
    if decision not in DECISIONS:
        raise DeviceJobError(REASON_DECISION_INVALID, 400)
    if decision == DECISION_ALLOW_JOB_EDITS and not approval.can_allow_job_edits:
        raise DeviceJobError(REASON_JOB_EDITS_NOT_ALLOWED, 400)
    if ensure_utc(approval.expires_at) <= utc_now_aware():
        await db.execute(update(DeviceJobApproval).where(DeviceJobApproval.id == approval.id,
                                                         DeviceJobApproval.status == "pending")
                         .values(status="expired"))
        await db.flush()
        record_device_approval(job, approval, status="expired")
        raise DeviceJobError(REASON_APPROVAL_EXPIRED, 409)
    result = await db.execute(
        update(DeviceJobApproval)
        .where(DeviceJobApproval.id == approval.id, DeviceJobApproval.status == "pending")
        .values(status=DECISIONS[decision], decided_by=user_id, decided_at=utc_now(), decision_state="pending")
    )
    if result.rowcount != 1:
        raise DeviceJobError(REASON_APPROVAL_DECIDED, 409)
    await db.refresh(approval)
    record_device_approval(job, approval, status=approval.status, actor_id=user_id)
    _audit(db, actor_id=user_id, action="device.approval.decided", job=job,
           details={"approval_id": approval.id, "tool": approval.tool, "decision": decision,
                    "input_digest": approval.input_digest})
    from .chat_confirmation import audit_confirmed_write

    await audit_confirmed_write(db, job, approval, decision)
    await db.flush()
    return approval


async def expire_due_approvals(db: AsyncSession, *, device_id: str) -> list[DeviceJobApproval]:
    rows = list((await db.execute(
        select(DeviceJobApproval).join(DeviceJob, DeviceJob.id == DeviceJobApproval.job_id).where(
            DeviceJob.device_id == device_id, DeviceJobApproval.status == "pending",
            DeviceJobApproval.expires_at <= utc_now())
    )).scalars().all())
    for approval in rows:
        approval.status = "expired"
        job = await db.get(DeviceJob, approval.job_id)
        if job is not None:
            record_device_approval(job, approval, status="expired")
    await db.flush()
    return rows


async def _approval_requested(db: AsyncSession, job: DeviceJob, body: dict[str, Any], *,
                              timeout_s: int, allow_job_edits: bool) -> DeviceJobApproval | None:
    request_id = str(body.get("approval_id") or "")[:64]
    if not request_id:
        return None
    existing = (await db.execute(select(DeviceJobApproval).where(
        DeviceJobApproval.job_id == job.id, DeviceJobApproval.request_id == request_id))).scalar_one_or_none()
    if existing is not None:
        return existing
    tool = str(body.get("tool") or "")[:120] or "unknown"
    preview = _clip(str(body.get("input_preview") or ""), MAX_PREVIEW_CHARS)
    from ..agent_gateway.decision_confirmation import device_decision_preview

    # A run decision shows the owner the platform's full ask text (payload hash first), not only the tool input.
    preview = await device_decision_preview(db, owner_user_id=job.owner_user_id, tool=tool, preview=preview) or preview
    approval = DeviceJobApproval(
        request_id=request_id, job_id=job.id, owner_user_id=job.owner_user_id, tool=tool,
        # The digest stays over the unmasked preview: a chat write confirmation matches it against the raw tool input.
        input_preview=masked_text(preview), input_digest=input_digest(preview),
        can_allow_job_edits=int(allow_job_edits and tool in EDIT_TOOLS),
        expires_at=utc_now() + timedelta(seconds=timeout_s),
    )
    db.add(approval)
    await db.flush()
    record_device_approval(job, approval, status="pending")
    _audit(db, actor_id=job.owner_user_id, action="device.approval.requested", job=job,
           details={"approval_id": approval.id, "tool": tool, "input_digest": approval.input_digest,
                    "expires_at": approval.expires_at.isoformat()})
    return approval

