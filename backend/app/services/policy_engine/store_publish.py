"""Publishing a policy-set version in review: the four-eyes gate, the saved test cases, then the swap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, PolicySetVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from ..access_control import _user_is_admin
from ..governance.four_eyes import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_SELF,
    SelfApprovalRefusedError,
    decide_four_eyes,
    record_self_approval_audit,
    self_approve_pending,
)
from .baseline import load_baseline
from .store import (
    AUDIT_PUBLISHED,
    AUDIT_RETIRED,
    REFUSAL_APPROVAL_MISMATCHED,
    REFUSAL_APPROVAL_MISSING,
    REFUSAL_APPROVAL_NOT_APPROVED,
    REFUSAL_APPROVAL_REQUIRED,
    REFUSAL_APPROVER_NOT_ADMIN,
    REFUSAL_NOT_IN_REVIEW,
    REFUSAL_SELF_APPROVAL,
    REFUSAL_TESTS_FAILED,
    PolicyStoreRefusalError,
    _audit,
    approval_action,
    published,
)
from .test_bench import CustomText
from .test_cases import run_cases


@dataclass(frozen=True, slots=True)
class PublishGate:
    approval_id: str
    requested_by: str
    approved_by: str
    single_admin: bool

    @property
    def approval_mode(self) -> str:
        return APPROVAL_MODE_SELF if self.single_admin else APPROVAL_MODE_FOUR_EYES

    def as_dict(self) -> dict[str, Any]:
        return {"status": "approved", "approval_id": self.approval_id, "requested_by": self.requested_by,
                "approved_by": self.approved_by, "single_admin_self_approval": self.single_admin,
                "approval_mode": self.approval_mode}


async def check_publish_gate(db: AsyncSession, row: PolicySetVersion, approval_id: str | None) -> PublishGate:
    if not approval_id:
        raise PolicyStoreRefusalError(REFUSAL_APPROVAL_REQUIRED)
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise PolicyStoreRefusalError(REFUSAL_APPROVAL_MISSING)
    if approval.action != approval_action(row) or approval.workspace_id is not None or approval.session_id:
        raise PolicyStoreRefusalError(REFUSAL_APPROVAL_MISMATCHED)
    if approval.status != "approved" or not approval.approved_by:
        raise PolicyStoreRefusalError(REFUSAL_APPROVAL_NOT_APPROVED, approval_status=str(approval.status or ""))
    approver = str(approval.approved_by)
    decision = await decide_four_eyes(db, approval.requested_by, approver, authors=(row.created_by, row.submitted_by))
    if not decision.approved:
        raise PolicyStoreRefusalError(REFUSAL_SELF_APPROVAL)
    if not await _user_is_admin(db, approver):
        raise PolicyStoreRefusalError(REFUSAL_APPROVER_NOT_ADMIN)
    record_self_approval_audit(db, decision, resource_type="policy_set_version", resource_id=row.id,
                               approval_id=approval.id, project_id=None)
    return PublishGate(approval.id, str(approval.requested_by), approver, decision.self_approved)


async def self_approve_review(db: AsyncSession, row: PolicySetVersion, *, actor_id: str) -> str:
    approval = await db.get(Approval, row.approval_id) if row.approval_id else None
    if approval is None:
        raise PolicyStoreRefusalError(REFUSAL_APPROVAL_REQUIRED)
    try:
        await self_approve_pending(db, approval, actor_id=actor_id)
    except SelfApprovalRefusedError as error:
        raise PolicyStoreRefusalError(REFUSAL_SELF_APPROVAL, reason=error.code) from None
    return approval.id


async def publish_version(
    db: AsyncSession, row: PolicySetVersion, *, approval_id: str | None, actor_id: str, self_approve: bool = False
) -> PublishGate:
    if row.state != REVISION_STATE_IN_REVIEW:
        raise PolicyStoreRefusalError(REFUSAL_NOT_IN_REVIEW)
    if self_approve and not approval_id:
        approval_id = await self_approve_review(db, row, actor_id=actor_id)
    gate = await check_publish_gate(db, row, approval_id)
    # The baseline and the entities may have changed since the save: the saved cases run again, and a failure blocks.
    report = await run_cases(db, CustomText(str(row.policies_text), f"version {row.version}"))
    if not report["ok"]:
        raise PolicyStoreRefusalError(REFUSAL_TESTS_FAILED, test_report=report)
    now = utc_now()
    previous = await published(db)
    if previous is not None:
        previous.state, previous.retired_by, previous.retired_at = REVISION_STATE_RETIRED, actor_id, now
        previous.updated_at = now
        _audit(db, actor_id, AUDIT_RETIRED, previous, replaced_by=row.version)
        await db.flush()
    baseline = await load_baseline(db)
    row.state, row.approval_id, row.published_by = REVISION_STATE_PUBLISHED, gate.approval_id, actor_id
    row.published_at, row.baseline_digest, row.updated_at = now, baseline.digest, now
    _audit(db, actor_id, AUDIT_PUBLISHED, row, approval_id=gate.approval_id, approved_by=gate.approved_by,
           baseline_digest=baseline.digest, previous_version=previous.version if previous is not None else None,
           approval_mode=gate.approval_mode)
    await db.flush()
    return gate


__all__ = ["PublishGate", "check_publish_gate", "publish_version", "self_approve_review"]
