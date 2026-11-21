"""Custom policy-set versions: draft → in_review → published → retired, four-eyes publish.

One instance-wide custom policy set, versioned. A draft is edited freely (every save is validated:
``custom_policies.check_custom_policies``); submitting freezes its text and digest and opens a governance
approval (the platform ``Approval`` row, ``workspace_id`` NULL so only platform admins see and decide it) whose
action binds the version id **and** its digest. Publishing then requires that approval ``approved`` by a
platform admin who is neither the version's author nor its submitter.

Whether the author or submitter may approve their own version is the platform approval rule, decided by the
shared four-eyes gate (``services.governance.four_eyes.decide_four_eyes``). Under the ``single_admin`` rule
``publish_version(..., self_approve=True)`` approves the pending review and publishes in one step; the publish
audit records ``approval_mode`` and a self-approval adds its own audit row.

Every draft save runs the saved test cases (``test_cases``) and stores the report on the version; publishing runs
them again and refuses with ``policy_set_tests_failed`` when one fails.

Publishing retires the previously published version in the same transaction, so at most one is published.
Rollback creates a new draft from any earlier version; it goes through review like every other draft.

A version also carries its custom content detectors and categories (``content_detectors``): validated on
every save and again on submit, covered by the digest, copied into a rollback draft — reviewed and published with
the policies they give meaning to.

Retiring the published version would drop every custom ``forbid`` at once, a widening one admin must not do
alone: :func:`retire_version` refuses it (``policy_set_retire_requires_review``). The reviewed way is a draft
with no policies, published through the same four-eyes gate (publishing retires the previous version). Only an
unpublished draft or a version in review may be retired directly (withdrawn). The publish step and its
four-eyes gate are ``store_publish``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_detection.custom_definitions import DetectorDefinitions
from app.services.content_detection.custom_validation import check_detector_set

from ...models import Approval, AuditLog, PolicySetVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from .custom_policies import ERROR_INVALID, CustomPolicyError, check_custom_policies, set_digest
from .schema import SCHEMA_VERSION
from .test_bench import CustomText
from .test_cases import run_cases

APPROVAL_KIND = "policy_set"
MAX_NOTE_CHARS = 500

AUDIT_DRAFT_SAVED = "policy_engine.policy_set_draft_saved"
AUDIT_SUBMITTED = "policy_engine.policy_set_submitted"
AUDIT_PUBLISHED = "policy_engine.policy_set_published"
AUDIT_RETIRED = "policy_engine.policy_set_retired"

REFUSAL_NOT_FOUND = "policy_set_version_not_found"
REFUSAL_NOT_DRAFT = "policy_set_version_not_draft"
REFUSAL_NOT_IN_REVIEW = "policy_set_version_not_in_review"
REFUSAL_ALREADY_RETIRED = "policy_set_version_retired"
REFUSAL_RETIRE_REQUIRES_REVIEW = "policy_set_retire_requires_review"
REFUSAL_APPROVAL_REQUIRED = "policy_set_approval_required"
REFUSAL_APPROVAL_MISSING = "policy_set_approval_missing"
REFUSAL_APPROVAL_MISMATCHED = "policy_set_approval_mismatched"
REFUSAL_APPROVAL_NOT_APPROVED = "policy_set_approval_not_approved"
REFUSAL_SELF_APPROVAL = "policy_set_self_approval"
REFUSAL_APPROVER_NOT_ADMIN = "policy_set_approver_not_platform_admin"
REFUSAL_TESTS_FAILED = "policy_set_tests_failed"


class PolicyStoreRefusalError(Exception):
    def __init__(self, code: str, status: int = 409, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details


def approval_action(row: PolicySetVersion) -> str:
    return f"{APPROVAL_KIND}.publish:{row.id}:{row.digest}"


def _note(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:MAX_NOTE_CHARS] or None


def _audit(db: AsyncSession, actor_id: str, action: str, row: PolicySetVersion, **details: Any) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, resource_type="policy_set_version", resource_id=row.id,
                    details={"version": row.version, "digest": row.digest, **details}))


async def list_versions(db: AsyncSession) -> list[PolicySetVersion]:
    return list((await db.execute(select(PolicySetVersion).order_by(PolicySetVersion.version.desc()))).scalars())


async def get_version(db: AsyncSession, version: int) -> PolicySetVersion:
    row = (
        await db.execute(select(PolicySetVersion).where(PolicySetVersion.version == int(version)))
    ).scalar_one_or_none()
    if row is None:
        raise PolicyStoreRefusalError(REFUSAL_NOT_FOUND, 404)
    return row


async def published(db: AsyncSession) -> PolicySetVersion | None:
    stmt = select(PolicySetVersion).where(PolicySetVersion.state == REVISION_STATE_PUBLISHED)
    return (await db.execute(stmt)).scalar_one_or_none()


def detector_definitions(row: PolicySetVersion | None) -> DetectorDefinitions:
    """The version's custom detectors (raises ``DetectorSetError`` when stored ones no longer validate)."""
    return check_detector_set(row.content_detectors if row is not None else None)


async def check_targets(db: AsyncSession, text: str, definitions: DetectorDefinitions) -> None:
    """Obligation targets and masks against the version's detectors and the active alias catalogs."""
    from .obligation_checks import check_obligation_targets
    from .policy_text import index_statements, split_statements
    from .runtime import alias_approvals

    if "@obligation" not in text or not split_statements(text).statements:
        return
    issues = check_obligation_targets(index_statements(text), definitions, await alias_approvals(db))
    if issues:
        raise CustomPolicyError(ERROR_INVALID, issues)


def _stored(definitions: DetectorDefinitions) -> dict[str, Any] | None:
    return None if definitions.empty else definitions.to_json()


async def create_draft(
    db: AsyncSession, *, text: Any, note: Any, actor_id: str, rollback_of: int | None = None,
    detectors: DetectorDefinitions | None = None,
) -> PolicySetVersion:
    """A new draft; raises ``CustomPolicyError`` when the text does not validate. Flushes."""
    checked = check_custom_policies(text)
    definitions = detectors or DetectorDefinitions()
    await check_targets(db, checked.text, definitions)
    latest = (await db.execute(select(func.max(PolicySetVersion.version)))).scalar_one_or_none() or 0
    current = await published(db)
    now = utc_now()
    row = PolicySetVersion(
        version=int(latest) + 1, state=REVISION_STATE_DRAFT, policies_text=checked.text,
        policy_ids=list(checked.ids), digest=set_digest(checked.text, definitions), schema_version=SCHEMA_VERSION,
        note=_note(note), content_detectors=_stored(definitions),
        base_version=current.version if current is not None else None, created_by=actor_id,
        created_at=now, updated_at=now,
    )
    db.add(row)
    await db.flush()
    row.test_report = await run_cases(db, CustomText(checked.text, f"draft version {row.version}"))
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, row, created=True, rollback_of=rollback_of)
    await db.flush()
    return row


async def save_draft(db: AsyncSession, row: PolicySetVersion, *, text: Any, note: Any, actor_id: str,
                     detectors: DetectorDefinitions | None = None) -> None:
    """Save the text (and, when given, the custom detectors; else they stay as they are)."""
    if row.state != REVISION_STATE_DRAFT:
        raise PolicyStoreRefusalError(REFUSAL_NOT_DRAFT)
    checked = check_custom_policies(text)
    definitions = detectors if detectors is not None else detector_definitions(row)
    await check_targets(db, checked.text, definitions)
    row.policies_text, row.policy_ids = checked.text, list(checked.ids)
    row.digest, row.content_detectors = set_digest(checked.text, definitions), _stored(definitions)
    row.schema_version, row.note, row.updated_at = SCHEMA_VERSION, _note(note), utc_now()
    row.test_report = await run_cases(db, CustomText(checked.text, f"draft version {row.version}"))
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, row, created=False)
    await db.flush()


async def save_note(db: AsyncSession, row: PolicySetVersion, *, note: Any, actor_id: str) -> None:
    """Change only the draft's note: the text (and its digest) is not re-sent, so no concurrent edit is lost."""
    if row.state != REVISION_STATE_DRAFT:
        raise PolicyStoreRefusalError(REFUSAL_NOT_DRAFT)
    row.note, row.updated_at = _note(note), utc_now()
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, row, created=False, note_only=True)
    await db.flush()


async def submit_version(db: AsyncSession, row: PolicySetVersion, *, actor_id: str) -> Approval:
    if row.state != REVISION_STATE_DRAFT:
        raise PolicyStoreRefusalError(REFUSAL_NOT_DRAFT)
    check_custom_policies(row.policies_text)  # the schema may have changed since the last save
    await check_targets(db, str(row.policies_text), detector_definitions(row))
    now = utc_now()
    row.state, row.submitted_by, row.submitted_at, row.updated_at = REVISION_STATE_IN_REVIEW, actor_id, now, now
    approval = Approval(requested_by=actor_id, workspace_id=None, action=approval_action(row), status="pending",
                        reason=f"Publish Cedar policy set version {row.version}")
    db.add(approval)
    await db.flush()
    row.approval_id = approval.id
    _audit(db, actor_id, AUDIT_SUBMITTED, row, approval_id=approval.id)
    await db.flush()
    return approval


async def retire_version(db: AsyncSession, row: PolicySetVersion, *, actor_id: str) -> None:
    """Withdraw a draft or a version in review; the published version is replaced only through review."""
    if row.state == REVISION_STATE_RETIRED:
        raise PolicyStoreRefusalError(REFUSAL_ALREADY_RETIRED)
    if row.state == REVISION_STATE_PUBLISHED:
        raise PolicyStoreRefusalError(REFUSAL_RETIRE_REQUIRES_REVIEW)
    now = utc_now()
    row.state, row.retired_by, row.retired_at, row.updated_at = REVISION_STATE_RETIRED, actor_id, now, now
    _audit(db, actor_id, AUDIT_RETIRED, row)
    await db.flush()


async def rollback_to(db: AsyncSession, version: int, *, actor_id: str) -> PolicySetVersion:
    source = await get_version(db, version)
    return await create_draft(db, text=source.policies_text, note=f"Rollback to version {source.version}",
                              actor_id=actor_id, rollback_of=source.version, detectors=detector_definitions(source))


def serialize_version(row: PolicySetVersion, *, include_text: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": row.version,
        "state": row.state,
        "digest": row.digest,
        "schema_version": row.schema_version,
        "policy_ids": list(row.policy_ids or []),
        "note": row.note,
        "base_version": row.base_version,
        "baseline_digest": row.baseline_digest,
        "test_report": row.test_report,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "submitted_by": row.submitted_by,
        "approval_id": row.approval_id,
        "published_by": row.published_by,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
    }
    if include_text:
        payload["policies"] = row.policies_text
        payload["content_detectors"] = row.content_detectors or {"categories": [], "detectors": []}
    return payload


__all__ = [
    "PolicyStoreRefusalError",
    "approval_action",
    "create_draft",
    "detector_definitions",
    "get_version",
    "list_versions",
    "published",
    "retire_version",
    "rollback_to",
    "save_draft",
    "save_note",
    "serialize_version",
    "submit_version",
]
