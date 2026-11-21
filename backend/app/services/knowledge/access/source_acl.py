"""Source ACL facets in the ledger: stored, re-checked, and projected.

PostgreSQL is the authority. A source is restricted when it has a ``KnowledgeSourceAcl`` row, and
readable only by the principal keys stored for it (``access/acl_keys.py``). This module owns:

- **the switch**: a Workspace ingests restricted items only when ``Project.config`` carries
  ``{"knowledge_source_acl": {"enforce": true}}``, read from the row itself and ``True`` only; any
  other value keeps today's behavior, where restricted items are withheld at sync;
- **the write** of one source's ACL, which a connector does *before* ingesting, so no revision of a
  restricted item ever exists without its restriction; and the re-projection an ACL change owes;
- **the re-check** (:func:`visible_source`): the SQL predicate every ledger read that returns
  content or titles applies, so a stale or missing projection marker can never widen access;
- **the marker** a projected span carries (:func:`span_marker_for_revision`).

Retrieval enforcement never depends on the switch: a restricted source stays filtered after the
switch is turned off, until a sync withholds and retires it.
"""

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
from .acl_keys import MAX_SOURCE_PRINCIPALS, normalize_email, principal_key_for_email, span_acl_keys

ACL_CONFIG_KEY = "knowledge_source_acl"
MAX_SOURCE_PRINCIPAL_LABELS = 20
MAX_RESTRICTION_CHARS = 40


@dataclass(frozen=True, slots=True)
class StoredSourceAcl:
    restriction: str
    principal_keys: frozenset[str]


async def acl_enforcement_enabled(db: AsyncSession, project_id: str) -> bool:
    """Whether this Workspace ingests restricted items with their ACL. Off unless explicitly ``True``."""
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    section = config.get(ACL_CONFIG_KEY) if isinstance(config, Mapping) else None
    return isinstance(section, Mapping) and section.get("enforce") is True


def visible_source(project_id: str, source_key: ColumnElement, principal_keys: tuple[str, ...]) -> ColumnElement:
    """SQL predicate: the source named by ``source_key`` is readable with ``principal_keys``."""
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
    """Store the source as restricted to ``member_emails`` (none: readable by nobody). True when it changed.

    Runs in the caller's transaction and never commits. Addresses are hashed here and not stored.
    """
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
    """The source is readable by the whole Workspace again. True when it was restricted."""
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
    """Owe the projection of the source again, so every span it serves carries the new marker.

    The current revision's completed projection is reopened from its first span, and every pending
    projection of the source restarts at its first span, so no span keeps the old marker. A claimed
    one is left to its holder (a fenced lease is never cleared from the side); until it reruns, the
    ledger re-check still decides. Runs in the caller's transaction and never commits. True when an
    obligation was reset.
    """
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


async def span_marker_for_revision(db: AsyncSession, project_id: str, revision_id: str) -> tuple[str, ...]:
    """The ACL marker every projected span of ``revision_id`` carries, read from the ledger."""
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
