"""The one four-eyes decision every governance-gated publish goes through."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings, get_settings
from ...four_eyes_dev_policy import dev_self_approval_environment_permitted
from ...models import Approval, AuditLog
from .approval_rule import APPROVAL_RULE_SINGLE_ADMIN, load_approval_rule

FOUR_EYES_APPROVED = "approved"
FOUR_EYES_APPROVED_SELF_APPROVAL = "approved_self_approval"
FOUR_EYES_APPROVED_DEV_SELF_APPROVAL = "approved_dev_self_approval"
FOUR_EYES_INVALID_SELF_APPROVAL = "invalid_self_approval"
FOUR_EYES_MISSING_APPROVER = "missing_approver"
FOUR_EYES_PASSING_STATUSES = frozenset(
    {FOUR_EYES_APPROVED, FOUR_EYES_APPROVED_SELF_APPROVAL, FOUR_EYES_APPROVED_DEV_SELF_APPROVAL}
)
FOUR_EYES_STATUSES = FOUR_EYES_PASSING_STATUSES | {FOUR_EYES_INVALID_SELF_APPROVAL, FOUR_EYES_MISSING_APPROVER}

APPROVAL_MODE_FOUR_EYES = "four_eyes"
APPROVAL_MODE_SELF = "self"
SELF_APPROVAL_SOURCE_RULE = "approval_rule"
SELF_APPROVAL_SOURCE_DEV = "dev_flag"

SELF_APPROVAL_AUDIT_ACTION = "governance.four_eyes.self_approval"
DEV_SELF_APPROVAL_AUDIT_ACTION = "governance.four_eyes.dev_self_approval"
SELF_APPROVAL_REASON = "Self-approved (approval rule: single admin)"
REFUSAL_SELF_APPROVAL_NOT_ALLOWED = "self_approval_not_allowed"
REFUSAL_NOT_PENDING = "approval_not_pending"
REFUSAL_REVIEW_MISSING = "review_approval_missing"


class SelfApprovalRefusedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FourEyesDecision:
    status: str
    requested_by: str | None
    approved_by: str | None
    dev_exception: bool
    approval_mode: str | None = None

    @property
    def approved(self) -> bool:
        return self.status in FOUR_EYES_PASSING_STATUSES

    @property
    def self_approved(self) -> bool:
        return self.approved and self.approval_mode == APPROVAL_MODE_SELF


def dev_self_approval_permitted(settings: Settings | None = None) -> bool:
    resolved = settings if settings is not None else get_settings()
    if getattr(resolved, "four_eyes_dev_self_approval", False) is not True:
        return False
    return dev_self_approval_environment_permitted(
        getattr(resolved, "runtime_profile", None),
        getattr(resolved, "cors_allowed_origins", None),
    )


async def self_approval_source(db: AsyncSession, settings: Settings | None = None) -> str | None:
    if await load_approval_rule(db) == APPROVAL_RULE_SINGLE_ADMIN:
        return SELF_APPROVAL_SOURCE_RULE
    if dev_self_approval_permitted(settings):
        return SELF_APPROVAL_SOURCE_DEV
    return None


def _normalized_user_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def evaluate_four_eyes(
    requested_by: str | None,
    approved_by: str | None,
    *,
    authors: Iterable[str | None] = (),
    self_approval: str | None = None,
    settings: Settings | None = None,
) -> FourEyesDecision:
    requester = _normalized_user_id(requested_by)
    approver = _normalized_user_id(approved_by)
    if approver is None:
        return FourEyesDecision(FOUR_EYES_MISSING_APPROVER, requester, None, False)
    own = {requester, *(_normalized_user_id(item) for item in authors)} - {None}
    if approver not in own:
        return FourEyesDecision(FOUR_EYES_APPROVED, requester, approver, False, APPROVAL_MODE_FOUR_EYES)
    if self_approval == SELF_APPROVAL_SOURCE_RULE:
        return FourEyesDecision(FOUR_EYES_APPROVED_SELF_APPROVAL, requester, approver, False, APPROVAL_MODE_SELF)
    if self_approval == SELF_APPROVAL_SOURCE_DEV or dev_self_approval_permitted(settings):
        return FourEyesDecision(FOUR_EYES_APPROVED_DEV_SELF_APPROVAL, requester, approver, True, APPROVAL_MODE_SELF)
    return FourEyesDecision(FOUR_EYES_INVALID_SELF_APPROVAL, requester, approver, False)


def recorded_approval_mode(approval: Approval | None, *, authors: Iterable[str | None] = ()) -> str | None:
    if approval is None or approval.status != "approved" or not approval.approved_by:
        return None
    own = {_normalized_user_id(approval.requested_by), *(_normalized_user_id(item) for item in authors)} - {None}
    return APPROVAL_MODE_SELF if _normalized_user_id(approval.approved_by) in own else APPROVAL_MODE_FOUR_EYES


async def decide_four_eyes(
    db: AsyncSession,
    requested_by: str | None,
    approved_by: str | None,
    *,
    authors: Iterable[str | None] = (),
) -> FourEyesDecision:
    return evaluate_four_eyes(
        requested_by, approved_by, authors=authors, self_approval=await self_approval_source(db)
    )


async def self_approve_pending(db: AsyncSession, approval: Approval, *, actor_id: str) -> Approval:
    from ..approval.resolution_service import decide_pending_approval

    if await self_approval_source(db) is None or str(approval.requested_by or "") != str(actor_id):
        raise SelfApprovalRefusedError(REFUSAL_SELF_APPROVAL_NOT_ALLOWED)
    decided = await decide_pending_approval(
        db, approval_id=approval.id, resolved_by=actor_id, status="approved", reason=SELF_APPROVAL_REASON
    )
    if decided is None:
        raise SelfApprovalRefusedError(REFUSAL_NOT_PENDING)
    return decided


async def self_approve_review(db: AsyncSession, approval_id: str | None, *, actor_id: str) -> str:
    approval = await db.get(Approval, approval_id) if approval_id else None
    if approval is None:
        raise SelfApprovalRefusedError(REFUSAL_REVIEW_MISSING)
    await self_approve_pending(db, approval, actor_id=actor_id)
    return approval.id


def record_self_approval_audit(
    db: AsyncSession,
    decision: FourEyesDecision,
    *,
    resource_type: str,
    resource_id: str,
    approval_id: str,
    project_id: str | None,
) -> None:
    if not decision.self_approved or decision.approved_by is None:
        return
    db.add(
        AuditLog(
            user_id=decision.approved_by,
            action=DEV_SELF_APPROVAL_AUDIT_ACTION if decision.dev_exception else SELF_APPROVAL_AUDIT_ACTION,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            details={
                "approval_id": approval_id,
                "requested_by": decision.requested_by,
                "approved_by": decision.approved_by,
                "four_eyes_status": decision.status,
                "approval_mode": APPROVAL_MODE_SELF,
            },
        )
    )


__all__ = [
    "APPROVAL_MODE_FOUR_EYES",
    "APPROVAL_MODE_SELF",
    "DEV_SELF_APPROVAL_AUDIT_ACTION",
    "FOUR_EYES_PASSING_STATUSES",
    "FOUR_EYES_STATUSES",
    "SELF_APPROVAL_AUDIT_ACTION",
    "FourEyesDecision",
    "SelfApprovalRefusedError",
    "decide_four_eyes",
    "dev_self_approval_permitted",
    "evaluate_four_eyes",
    "record_self_approval_audit",
    "recorded_approval_mode",
    "self_approval_source",
    "self_approve_pending",
    "self_approve_review",
]
