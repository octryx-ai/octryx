"""Governance approvals and audit for registry publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, AuditLog
from ..access_control import get_project_role_for_user
from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes, record_self_approval_audit

KIND_MODEL_POLICY = "model_policy"

APPROVAL_STATUS_APPROVED = "approved"


def publish_approval_action(kind: str, revision_id: str, digest: str) -> str:
    return f"{kind}.publish:{revision_id}:{digest}"


@dataclass(frozen=True, slots=True)
class ApprovalGate:
    status: str
    approval_id: str | None
    requested_by: str | None = None
    approved_by: str | None = None
    dev_self_approval: bool = False
    approval_mode: str | None = None

    @property
    def passed(self) -> bool:
        return self.status in FOUR_EYES_PASSING_STATUSES

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "approval_id": self.approval_id,
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
        }
        if self.dev_self_approval:
            payload["dev_self_approval"] = True
        if self.approval_mode:
            payload["approval_mode"] = self.approval_mode
        return payload


async def create_review_approval(
    db: AsyncSession, *, kind: str, workspace_id: str, revision_id: str, digest: str, requested_by: str, label: str
) -> Approval:
    approval = Approval(
        requested_by=requested_by,
        workspace_id=workspace_id,  # seen and decided inside this Workspace only
        action=publish_approval_action(kind, revision_id, digest),
        status="pending",
        reason=f"Publish {kind} {label}",
    )
    db.add(approval)
    await db.flush()
    return approval


APPROVER_PROJECT_ROLES = frozenset({"admin", "owner"})


async def check_publish_approval(
    db: AsyncSession, *, kind: str, workspace_id: str, revision_id: str, digest: str, approval_id: str | None
) -> ApprovalGate:
    if not approval_id:
        return ApprovalGate("required", None)
    approval = await db.get(Approval, approval_id)
    if approval is None:
        return ApprovalGate("missing", approval_id)
    if approval.action != publish_approval_action(kind, revision_id, digest) or approval.workspace_id != workspace_id:
        return ApprovalGate("mismatched", approval.id)
    if approval.status != APPROVAL_STATUS_APPROVED:
        return ApprovalGate(str(approval.status or "pending"), approval.id, approval.requested_by)
    decision = await decide_four_eyes(db, approval.requested_by, approval.approved_by)
    if decision.approved:
        role = await get_project_role_for_user(db, str(approval.approved_by), workspace_id)
        if role not in APPROVER_PROJECT_ROLES:
            return ApprovalGate("approver_not_authorized", approval.id, approval.requested_by, approval.approved_by)
        # Same transaction as the publish that relies on it (no-op unless self-approved).
        record_self_approval_audit(
            db, decision, resource_type=f"{kind}_revision", resource_id=revision_id, approval_id=approval.id,
            project_id=workspace_id,
        )
    return ApprovalGate(
        decision.status,
        approval.id,
        approval.requested_by,
        approval.approved_by,
        decision.dev_exception,
        decision.approval_mode if decision.approved else None,
    )


async def record_audit(
    db: AsyncSession, *, user_id: str, action: str, resource_type: str, resource_id: str, project_id: str | None,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            details=details,
        )
    )
    await db.flush()


__all__ = [
    "KIND_MODEL_POLICY",
    "ApprovalGate",
    "check_publish_approval",
    "create_review_approval",
    "publish_approval_action",
    "record_audit",
]
