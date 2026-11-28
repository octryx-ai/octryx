"""Governed revision lifecycle: submit for review, four-eyes publish, retire."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...time_utils import utc_now
from ..governance.four_eyes import SelfApprovalRefusedError, self_approve_review
from .errors import (
    APPROVAL_REFUSED,
    APPROVAL_REQUIRED,
    DIGEST_CHANGED,
    REVISION_ALREADY_RETIRED,
    REVISION_NOT_DRAFT,
    REVISION_NOT_IN_REVIEW,
    RegistryRefusalError,
)
from .governance import check_publish_approval, create_review_approval, record_audit

Precheck = Callable[[], Awaitable[None]]
DigestFn = Callable[[], str]


def _require_digest_intact(revision: Any, recompute_digest: DigestFn) -> None:
    if recompute_digest() != revision.digest:
        raise RegistryRefusalError(DIGEST_CHANGED, revision=revision.revision)


async def submit_revision(
    db: AsyncSession,
    *,
    kind: str,
    parent_id: str,
    workspace_id: str,
    label: str,
    revision: Any,
    user: User,
    recompute_digest: DigestFn,
    precheck: Precheck,
) -> Any:
    if revision.state != REVISION_STATE_DRAFT:
        raise RegistryRefusalError(REVISION_NOT_DRAFT, revision=revision.revision, state=revision.state)
    _require_digest_intact(revision, recompute_digest)
    await precheck()
    approval = await create_review_approval(
        db,
        kind=kind,
        workspace_id=workspace_id,
        revision_id=revision.id,
        digest=revision.digest,
        requested_by=user.id,
        label=f"{label}@{revision.revision}",
    )
    now = utc_now()
    revision.state = REVISION_STATE_IN_REVIEW
    revision.submitted_by = user.id
    revision.submitted_at = now
    revision.approval_id = approval.id
    revision.updated_at = now
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action=f"{kind}.submit",
        resource_type=kind,
        resource_id=parent_id,
        project_id=workspace_id,
        details={"revision": revision.revision, "digest": revision.digest, "approval_id": approval.id},
    )
    return revision


async def publish_revision(
    db: AsyncSession,
    *,
    kind: str,
    parent_id: str,
    workspace_id: str,
    revision: Any,
    approval_id: str | None,
    user: User,
    recompute_digest: DigestFn,
    precheck: Precheck,
    self_approve: bool = False,
) -> dict[str, Any]:
    if revision.state != REVISION_STATE_IN_REVIEW:
        raise RegistryRefusalError(REVISION_NOT_IN_REVIEW, revision=revision.revision, state=revision.state)
    _require_digest_intact(revision, recompute_digest)
    await precheck()
    if self_approve and not approval_id:
        try:
            approval_id = await self_approve_review(db, revision.approval_id, actor_id=user.id)
        except SelfApprovalRefusedError as error:
            raise RegistryRefusalError(APPROVAL_REFUSED, revision=revision.revision, reason=error.code) from None
    gate = await check_publish_approval(
        db,
        kind=kind,
        workspace_id=workspace_id,
        revision_id=revision.id,
        digest=revision.digest,
        approval_id=approval_id,
    )
    if gate.status == "required":
        raise RegistryRefusalError(
            APPROVAL_REQUIRED, revision=revision.revision, pending_approval_id=revision.approval_id
        )
    if not gate.passed:
        raise RegistryRefusalError(APPROVAL_REFUSED, revision=revision.revision, approval_gate=gate.as_dict())
    now = utc_now()
    revision.state = REVISION_STATE_PUBLISHED
    revision.approval_id = gate.approval_id
    revision.published_by = user.id
    revision.published_at = now
    revision.updated_at = now
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action=f"{kind}.publish",
        resource_type=kind,
        resource_id=parent_id,
        project_id=workspace_id,
        details={"revision": revision.revision, "digest": revision.digest, "approval_gate": gate.as_dict()},
    )
    return gate.as_dict()


async def retire_revision(
    db: AsyncSession, *, kind: str, parent_id: str, workspace_id: str, revision: Any, user: User
) -> Any:
    if revision.state == REVISION_STATE_RETIRED:
        raise RegistryRefusalError(REVISION_ALREADY_RETIRED, revision=revision.revision)
    previous = revision.state
    now = utc_now()
    revision.state = REVISION_STATE_RETIRED
    revision.retired_by = user.id
    revision.retired_at = now
    revision.updated_at = now
    await db.flush()
    await record_audit(
        db,
        user_id=user.id,
        action=f"{kind}.retire",
        resource_type=kind,
        resource_id=parent_id,
        project_id=workspace_id,
        details={"revision": revision.revision, "digest": revision.digest, "previous_state": previous},
    )
    return revision


__all__ = ["publish_revision", "retire_revision", "submit_revision"]
