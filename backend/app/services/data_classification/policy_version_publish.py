"""Approving, publishing, rejecting and rolling back a classification policy version."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ClassificationPolicyVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from ..access_control import _user_is_admin
from ..governance.four_eyes import decide_four_eyes, record_self_approval_audit, self_approval_source
from ..knowledge.projection.workspace_classification_default import set_instance_default
from .effect_rules import publish_effect_rules, rules_from_content
from .level_catalog import content_registry, publish_catalog
from .policy_matrix_admin import set_classification_policy
from .policy_version_content import (
    AUDIT_PUBLISHED,
    AUDIT_REJECTED,
    REFUSAL_APPROVER_NOT_ADMIN,
    REFUSAL_NOT_IN_REVIEW,
    REFUSAL_REVIEW_DECIDED,
    REFUSAL_SELF_APPROVAL,
    REFUSAL_TESTS_FAILED,
    ClassificationVersionError,
    stored_default_level,
)
from .policy_version_drafts import run_draft_cases, save_draft
from .policy_version_store import (
    _audit,
    _note,
    get_version,
    published_version,
)


async def approve_and_publish(db: AsyncSession, version: int, *, actor_id: str) -> ClassificationPolicyVersion:
    from ..approval.resolution_service import decide_pending_approval

    row = await get_version(db, version)
    if row.state != REVISION_STATE_IN_REVIEW or not row.approval_id:
        raise ClassificationVersionError(REFUSAL_NOT_IN_REVIEW)
    if not await _user_is_admin(db, actor_id):
        raise ClassificationVersionError(REFUSAL_APPROVER_NOT_ADMIN, 403)
    approval = await db.get(Approval, row.approval_id)
    if approval is None or approval.status not in {"pending", "approved"}:
        raise ClassificationVersionError(REFUSAL_REVIEW_DECIDED)
    approver = str(approval.approved_by) if approval.status == "approved" and approval.approved_by else actor_id
    decision = await decide_four_eyes(db, approval.requested_by, approver, authors=(row.created_by, row.submitted_by))
    if not decision.approved:
        raise ClassificationVersionError(REFUSAL_SELF_APPROVAL, 403)
    report = await run_draft_cases(db, row.content)
    if not report["ok"]:
        row.test_report = report
        await db.flush()
        raise ClassificationVersionError(REFUSAL_TESTS_FAILED, test_report=report)
    if approval.status == "pending":
        decided = await decide_pending_approval(db, approval_id=approval.id, resolved_by=actor_id, status="approved",
                                                reason=f"Approved classification policy version {row.version}")
        if decided is None:
            raise ClassificationVersionError(REFUSAL_REVIEW_DECIDED)
    record_self_approval_audit(db, decision, resource_type="classification_policy_version", resource_id=row.id,
                               approval_id=approval.id, project_id=None)
    await _apply_content(db, row.content, actor_id=actor_id)
    now = utc_now()
    previous = await published_version(db)
    if previous is not None:
        previous.state, previous.retired_by, previous.retired_at, previous.updated_at = (
            REVISION_STATE_RETIRED, actor_id, now, now)
        await db.flush()
    row.state, row.published_by, row.published_at, row.updated_at = REVISION_STATE_PUBLISHED, actor_id, now, now
    row.test_report = report
    _audit(db, actor_id, AUDIT_PUBLISHED, row, approval_id=approval.id, approved_by=decision.approved_by,
           approval_mode=decision.approval_mode,
           previous_version=previous.version if previous is not None else None)
    await db.flush()
    return row


async def _apply_content(db: AsyncSession, content: Mapping[str, Any], *, actor_id: str) -> None:
    if isinstance(content.get("level_catalog"), list):
        await publish_catalog(db, content_registry(content), actor_id=actor_id)
    await publish_effect_rules(db, rules_from_content(content), actor_id=actor_id)
    overrides = content.get("overrides") or {}
    await set_classification_policy(db, levels=[{"level": level, "rules": rules} for level, rules in overrides.items()],
                                    actor_id=actor_id)
    if content.get("default_level") != await stored_default_level(db):
        await set_instance_default(db, classification=content.get("default_level"), actor_id=actor_id,
                                   apply_to_unclassified=False)


async def reject_version(db: AsyncSession, version: int, *, comment: Any, actor_id: str) -> ClassificationPolicyVersion:
    from ..approval.resolution_service import decide_pending_approval

    row = await get_version(db, version)
    if row.state != REVISION_STATE_IN_REVIEW or not row.approval_id:
        raise ClassificationVersionError(REFUSAL_NOT_IN_REVIEW)
    if not await _user_is_admin(db, actor_id):
        raise ClassificationVersionError(REFUSAL_APPROVER_NOT_ADMIN, 403)
    reason = _note(comment) or f"Rejected classification policy version {row.version}"
    decided = await decide_pending_approval(db, approval_id=row.approval_id, resolved_by=actor_id, status="rejected",
                                            reason=reason)
    if decided is None:
        raise ClassificationVersionError(REFUSAL_REVIEW_DECIDED)
    row.state, row.updated_at = REVISION_STATE_DRAFT, utc_now()
    _audit(db, actor_id, AUDIT_REJECTED, row, approval_id=row.approval_id, comment=reason)
    row.approval_id, row.submitted_by, row.submitted_at = None, None, None
    await db.flush()
    return row


async def rollback_to(db: AsyncSession, version: int, *, actor_id: str) -> ClassificationPolicyVersion:
    source = await get_version(db, version)
    content = dict(source.content)
    return await save_draft(db, levels=[{"level": level, "rules": rules}
                                        for level, rules in (content.get("overrides") or {}).items()],
                            default_level=content.get("default_level"), note=f"Rollback to version {source.version}",
                            actor_id=actor_id, level_catalog=content.get("level_catalog"),
                            effect_rules=content.get("effect_rules") or [])


async def can_self_approve(db: AsyncSession) -> bool:
    return await self_approval_source(db) is not None
