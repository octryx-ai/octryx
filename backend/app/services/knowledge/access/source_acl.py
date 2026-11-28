"""Source ACL facets in the ledger: stored, re-checked, and projected. The ACL is written before ingesting; retrieval
enforcement never depends on the enforce switch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ....models import Project, User
from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_PROJECT_REVISION,
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_PENDING,
    KnowledgeEvidenceSource,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_source_acl import KnowledgeSourceAcl, KnowledgeSourceAclPrincipal
from ....time_utils import utc_now
from ..ledger.errors import EvidenceLedgerContractError
from .acl_keys import MAX_SOURCE_PRINCIPALS, AclKey, normalize_email, principal_key_for_email, span_acl_keys

ACL_CONFIG_KEY = "knowledge_source_acl"
MAX_SOURCE_PRINCIPAL_LABELS = 20
MAX_RESTRICTION_CHARS = 40


@dataclass(frozen=True, slots=True)
class StoredSourceAcl:
    restriction: str
    principal_keys: frozenset[str]


async def acl_enforcement_enabled(db: AsyncSession, project_id: str) -> bool:
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    section = config.get(ACL_CONFIG_KEY) if isinstance(config, Mapping) else None
    return isinstance(section, Mapping) and section.get("enforce") is True


def visible_source(project_id: str, source_key: ColumnElement, principal_keys: tuple[str, ...]) -> ColumnElement:
    unrestricted = ~exists().where(
        KnowledgeSourceAcl.project_id == project_id, KnowledgeSourceAcl.source_key == source_key
    )
    if not principal_keys:
        return unrestricted
    admitted = exists().where(
        KnowledgeSourceAclPrincipal.project_id == project_id,
        KnowledgeSourceAclPrincipal.source_key == source_key,
        KnowledgeSourceAclPrincipal.principal_key.in_(principal_keys),
    )
    return or_(unrestricted, admitted)


async def load_source_acl(db: AsyncSession, project_id: str, source_key: str) -> StoredSourceAcl | None:
    row = await db.get(KnowledgeSourceAcl, (project_id, source_key))
    if row is None:
        return None
    keys = (
        await db.execute(
            select(KnowledgeSourceAclPrincipal.principal_key).where(
                KnowledgeSourceAclPrincipal.project_id == project_id,
                KnowledgeSourceAclPrincipal.source_key == source_key,
            )
        )
    ).scalars()
    return StoredSourceAcl(row.restriction, frozenset(keys))


async def _matched_users(db: AsyncSession, emails: tuple[str, ...]) -> int:
    if not emails:
        return 0
    statement = select(func.count(User.id)).where(
        func.lower(User.email).in_(emails), User.is_active.is_(True), User.account_type == "human"
    )
    return int((await db.execute(statement)).scalar_one() or 0)


async def restrict_source(
    db: AsyncSession,
    *,
    project_id: str,
    source_key: str,
    restriction: str,
    source_principals: tuple[str, ...] = (),
    member_emails: tuple[str, ...] = (),
) -> bool:
    # Runs in the caller's transaction and never commits; addresses are hashed, never stored.
    if type(restriction) is not str or not 0 < len(restriction) <= MAX_RESTRICTION_CHARS:
        raise EvidenceLedgerContractError()
    emails = tuple(sorted({email for email in map(normalize_email, member_emails) if email is not None}))
    if len(emails) > MAX_SOURCE_PRINCIPALS:
        raise EvidenceLedgerContractError()
    keys = frozenset(key for key in map(principal_key_for_email, emails) if key is not None)
    previous = await load_source_acl(db, project_id, source_key)
    changed = previous is None or previous.principal_keys != keys
    row = await db.get(KnowledgeSourceAcl, (project_id, source_key))
    if row is None:
        row = KnowledgeSourceAcl(project_id=project_id, source_key=source_key)
        db.add(row)
    row.restriction = restriction
    row.source_principals = [str(label)[:120] for label in source_principals[:MAX_SOURCE_PRINCIPAL_LABELS]]
    row.principal_count = len(keys)
    row.matched_user_count = await _matched_users(db, emails)
    row.updated_at = utc_now()
    if changed:
        await _delete_principals(db, project_id, source_key)
        db.add_all(
            KnowledgeSourceAclPrincipal(project_id=project_id, source_key=source_key, principal_key=key)
            for key in sorted(keys)
        )
    await db.flush()
    return changed


async def unrestrict_source(db: AsyncSession, *, project_id: str, source_key: str) -> bool:
    row = await db.get(KnowledgeSourceAcl, (project_id, source_key))
    if row is None:
        return False
    await _delete_principals(db, project_id, source_key)
    await db.delete(row)
    await db.flush()
    return True


async def _delete_principals(db: AsyncSession, project_id: str, source_key: str) -> None:
    await db.execute(
        delete(KnowledgeSourceAclPrincipal).where(
            KnowledgeSourceAclPrincipal.project_id == project_id,
            KnowledgeSourceAclPrincipal.source_key == source_key,
        )
    )


async def _reopen_applied_projection(
    db: AsyncSession, projection: tuple[ColumnElement[bool], ...], revision_id: str
) -> int:
    reopened = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            *projection,
            KnowledgeProjectionOutboxEntry.revision_id == revision_id,
            KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_APPLIED,
        )
        .values(
            state=OUTBOX_STATE_PENDING,
            attempt_count=0,
            projected_through_ordinal=0,
            next_attempt_at=utc_now(),
            last_failure=None,
            claimed_by=None,
            claimed_at=None,
            claimed_until=None,
            applied_at=None,
        )
    )
    return reopened.rowcount or 0


async def reproject_source(db: AsyncSession, *, project_id: str, source_key: str) -> bool:
    # A claimed obligation is left to its holder: a fenced lease is never cleared from the side.
    head = (
        await db.execute(
            select(KnowledgeSourceHead.source_id, KnowledgeSourceHead.current_revision_id)
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceHead.source_id)
            .where(
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeEvidenceSource.source_key == source_key,
                KnowledgeSourceHead.project_id == project_id,
            )
        )
    ).first()
    if head is None:
        return False
    source_id, current_revision_id = head
    revisions = select(KnowledgeSourceRevision.id).where(
        KnowledgeSourceRevision.project_id == project_id, KnowledgeSourceRevision.source_id == source_id
    )
    projection = (
        KnowledgeProjectionOutboxEntry.project_id == project_id,
        KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_PROJECT_REVISION,
    )
    reset = 0
    if current_revision_id is not None:
        reset += await _reopen_applied_projection(db, projection, current_revision_id)
    restarted = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            *projection,
            KnowledgeProjectionOutboxEntry.revision_id.in_(revisions),
            KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_PENDING,
            KnowledgeProjectionOutboxEntry.projected_through_ordinal > 0,
        )
        .values(projected_through_ordinal=0)
        .execution_options(synchronize_session=False)
    )
    return bool(reset or restarted.rowcount)


async def span_marker_for_revision(db: AsyncSession, project_id: str, revision_id: str) -> tuple[AclKey, ...]:
    source_key = (
        await db.execute(
            select(KnowledgeEvidenceSource.source_key)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.source_id == KnowledgeEvidenceSource.id)
            .where(
                KnowledgeSourceRevision.id == revision_id,
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSource.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if source_key is None:
        raise EvidenceLedgerContractError()
    stored = await load_source_acl(db, project_id, source_key)
    return span_acl_keys(None if stored is None else tuple(stored.principal_keys))


__all__ = [
    "ACL_CONFIG_KEY",
    "StoredSourceAcl",
    "acl_enforcement_enabled",
    "load_source_acl",
    "reproject_source",
    "restrict_source",
    "span_marker_for_revision",
    "unrestrict_source",
    "visible_source",
]
