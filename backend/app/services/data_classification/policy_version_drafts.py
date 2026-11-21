"""Saving, discarding and submitting a classification policy draft."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ClassificationPolicyVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from .level_catalog import content_scope
from .policy_version_content import (
    AUDIT_DRAFT_DISCARDED,
    AUDIT_DRAFT_SAVED,
    AUDIT_SUBMITTED,
    REFUSAL_IN_REVIEW,
    REFUSAL_NO_CHANGES,
    REFUSAL_NO_DRAFT,
    REFUSAL_TESTS_FAILED,
    ClassificationVersionError,
    content_digest,
    normalized_content,
)
from .policy_version_store import (
    _audit,
    _next_version,
    _note,
    approval_action,
    base_content,
    open_draft,
    published_version,
)


async def save_draft(db: AsyncSession, *, levels: Any, default_level: Any, note: Any, actor_id: str,
                     level_catalog: Any = None, effect_rules: Any = None) -> ClassificationPolicyVersion:
    """Create or replace the open draft. Raises ``ClassificationPolicyError``, ``LevelCatalogError`` or
    ``ClassificationVersionError``."""
    base = await base_content(db)
    content = await normalized_content(db, levels=levels, default_level=default_level, base=base,
                                       level_catalog=level_catalog, effect_rules=effect_rules)
    row = await open_draft(db)
    if row is not None and row.state == REVISION_STATE_IN_REVIEW:
        raise ClassificationVersionError(REFUSAL_IN_REVIEW)
    now = utc_now()
    published = await published_version(db)
    if row is None:
        row = ClassificationPolicyVersion(version=await _next_version(db), state=REVISION_STATE_DRAFT,
                                          created_by=actor_id, created_at=now,
                                          base_version=published.version if published is not None else None)
        db.add(row)
    from .policy_preview import change_lines

    row.content, row.digest, row.note = content, content_digest(content), _note(note)
    row.changes = change_lines(base, content)
    row.updated_at, row.test_report = now, None
    await db.flush()
    _audit(db, actor_id, AUDIT_DRAFT_SAVED, row)
    await db.flush()
    return row


async def discard_draft(db: AsyncSession, *, actor_id: str) -> None:
    """Withdraw the open draft or review (it is kept as retired history)."""
    row = await open_draft(db)
    if row is None:
        raise ClassificationVersionError(REFUSAL_NO_DRAFT, 404)
    if row.approval_id:
        from ..approval.resolution_service import decide_pending_approval

        await decide_pending_approval(db, approval_id=row.approval_id, resolved_by=actor_id, status="rejected",
                                      reason="Withdrawn by the author")
    now = utc_now()
    row.state, row.retired_by, row.retired_at, row.updated_at = REVISION_STATE_RETIRED, actor_id, now, now
    _audit(db, actor_id, AUDIT_DRAFT_DISCARDED, row)
    await db.flush()


async def run_draft_cases(db: AsyncSession, content: Mapping[str, Any]) -> dict[str, Any]:
    """The saved policy test cases, with the published custom policies, against ``content``'s matrix."""
    from ..policy_engine.test_bench import custom_text
    from ..policy_engine.test_cases import run_cases

    custom = await custom_text(db, None)
    with content_scope(content):
        return await run_cases(db, custom)



async def submit_draft(db: AsyncSession, *, note: Any, actor_id: str) -> ClassificationPolicyVersion:
    row = await open_draft(db)
    if row is None:
        raise ClassificationVersionError(REFUSAL_NO_DRAFT, 404)
    if row.state != REVISION_STATE_DRAFT:
        raise ClassificationVersionError(REFUSAL_IN_REVIEW)
    if row.digest == content_digest(await base_content(db)):
        raise ClassificationVersionError(REFUSAL_NO_CHANGES)
    report = await run_draft_cases(db, row.content)
    row.test_report = report
    if not report["ok"]:
        await db.flush()
        raise ClassificationVersionError(REFUSAL_TESTS_FAILED, test_report=report)
    now = utc_now()
    row.state, row.submitted_by, row.submitted_at, row.updated_at = REVISION_STATE_IN_REVIEW, actor_id, now, now
    if note is not None:
        row.note = _note(note)
    approval = Approval(requested_by=actor_id, workspace_id=None, action=approval_action(row), status="pending",
                        reason=f"Publish classification policy version {row.version}")
    db.add(approval)
    await db.flush()
    row.approval_id = approval.id
    _audit(db, actor_id, AUDIT_SUBMITTED, row, approval_id=approval.id)
    await db.flush()
    return row
