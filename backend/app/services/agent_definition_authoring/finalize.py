"""Finalizing a governed write: one revision and one audit row per collected definition."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_revision_store import insert_revision, load_definition_steps

from ...models import AgentDefinition, AgentDefinitionRevision, AuditLog
from ...models.agent.agent_definition_revision import (
    REVISION_STATUS_DRAFT,
    REVISION_STATUS_INVALID,
    REVISION_STATUS_PUBLISHED,
)
from ...time_utils import utc_now
from ..agent_definition_revisions import next_revision_number
from ..agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum
from ..agent_definition_validation import validate_definition_snapshot
from ..agent_definition_writers import writer_spec
from .scope import (
    AUDIT_ACTION,
    AUDIT_RESOURCE_TYPE,
    OUTCOME_DELETED,
    OUTCOME_INVALID,
    OUTCOME_PUBLISHED,
    OUTCOME_RECORDED,
    OUTCOME_UNCHANGED,
    GovernedWriteRecord,
    GovernedWriteScope,
    _TouchedDefinitions,
)

# Log under the package's logger name.
logger = logging.getLogger(__package__)


async def _finalize(
    db: AsyncSession, *, scope: GovernedWriteScope, touched: _TouchedDefinitions
) -> None:
    for definition_id in sorted(touched.written):
        record = await _finalize_definition(
            db,
            scope=scope,
            definition_id=definition_id,
            deleted=definition_id in touched.deleted,
            captured_project_id=touched.project_ids.get(definition_id),
        )
        scope.records.append(record)
        await _write_audit(db, scope=scope, record=record)
    if scope.records:
        await db.flush()


def _deleted_record(
    scope: GovernedWriteScope, definition_id: str, captured_project_id: str | None
) -> GovernedWriteRecord:
    return GovernedWriteRecord(
        definition_id=definition_id,
        writer=scope.writer,
        outcome=OUTCOME_DELETED,
        project_id=captured_project_id or None,
    )


def _revision_outcome(scope: GovernedWriteScope, validation: Any) -> tuple[bool, str, str]:
    """Whether the revision is published, and its status and audit outcome."""
    publishes = writer_spec(scope.writer).publishes and validation.ok
    if publishes:
        return publishes, REVISION_STATUS_PUBLISHED, OUTCOME_PUBLISHED
    if validation.ok:
        return publishes, REVISION_STATUS_DRAFT, OUTCOME_RECORDED
    return publishes, REVISION_STATUS_INVALID, OUTCOME_INVALID


async def _append_revision(
    db: AsyncSession,
    *,
    scope: GovernedWriteScope,
    definition_id: str,
    snapshot: Any,
    checksum: str,
    validation: Any,
    status: str,
    publishes: bool,
) -> AgentDefinitionRevision:
    now = utc_now()
    revision = AgentDefinitionRevision(
        id=str(uuid.uuid4()),
        definition_id=definition_id,
        revision_number=await next_revision_number(db, definition_id),
        status=status,
        checksum=checksum,
        created_by=scope.actor_id,
        created_at=now,
        published_by=scope.actor_id if publishes else None,
        published_at=now if publishes else None,
    )
    revision.snapshot = snapshot
    revision.validation = validation.as_dict()
    await insert_revision(db, revision)
    return revision


async def _finalize_definition(
    db: AsyncSession,
    *,
    scope: GovernedWriteScope,
    definition_id: str,
    deleted: bool,
    captured_project_id: str | None,
) -> GovernedWriteRecord:
    """One record per collected definition — every governed write is evidence."""
    # A deleted definition is audited with the Workspace captured before the row
    # went away, so the deletion record keeps its project attribution.
    if deleted:
        return _deleted_record(scope, definition_id, captured_project_id)
    definition = await db.get(AgentDefinition, definition_id)
    if definition is None:
        # A step write whose definition disappeared in the same transaction.
        return _deleted_record(scope, definition_id, captured_project_id)

    steps = await load_definition_steps(db, definition_id)
    snapshot = build_definition_snapshot(definition, steps)
    checksum = compute_snapshot_checksum(snapshot)
    latest = await _newest_revision(db, definition_id)
    if latest is not None and latest.checksum == checksum:
        # Content-identical governed write: no revision is appended, because the
        # newest revision already *is* this content. It is still audited, as the
        # explicit ``unchanged`` outcome — a governed write that leaves no
        # evidence at all would be indistinguishable from an ungoverned one.
        return GovernedWriteRecord(
            definition_id=definition_id,
            writer=scope.writer,
            outcome=OUTCOME_UNCHANGED,
            revision_id=latest.id,
            revision_number=int(latest.revision_number),
            revision_status=str(latest.status or ""),
            project_id=str(definition.project_id or "") or None,
            checksum=checksum,
        )

    validation = await validate_definition_snapshot(db, snapshot)
    publishes, status, outcome = _revision_outcome(scope, validation)
    revision = await _append_revision(
        db, scope=scope, definition_id=definition_id, snapshot=snapshot, checksum=checksum,
        validation=validation, status=status, publishes=publishes,
    )
    _warn_unpublishable_seed(scope, definition_id, validation)
    return GovernedWriteRecord(
        definition_id=definition_id,
        writer=scope.writer,
        outcome=outcome,
        revision_id=revision.id,
        revision_number=int(revision.revision_number),
        revision_status=status,
        project_id=str(definition.project_id or "") or None,
        checksum=checksum,
        issue_codes=tuple(sorted({issue.code for issue in validation.issues})),
    )


def _warn_unpublishable_seed(scope: GovernedWriteScope, definition_id: str, validation: Any) -> None:
    if not validation.ok and writer_spec(scope.writer).publishes:
        # A shipped seed that cannot be published is a build-time defect, but
        # failing application start on it would be worse than starting with the
        # definition unpublished. Only typed codes are logged.
        logger.warning(
            "agent definition seed %s recorded as invalid by writer %s: %s",
            definition_id,
            scope.writer.value,
            sorted({issue.code for issue in validation.issues}),
        )


async def _newest_revision(
    db: AsyncSession, definition_id: str
) -> AgentDefinitionRevision | None:
    return (
        await db.execute(
            select(AgentDefinitionRevision)
            .where(AgentDefinitionRevision.definition_id == definition_id)
            .order_by(AgentDefinitionRevision.revision_number.desc())
            .limit(1)
        )
    ).scalars().first()


async def _write_audit(
    db: AsyncSession, *, scope: GovernedWriteScope, record: GovernedWriteRecord
) -> None:
    spec = writer_spec(scope.writer)
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=scope.actor_id,
            action=AUDIT_ACTION,
            resource_type=AUDIT_RESOURCE_TYPE,
            resource_id=record.definition_id,
            details={
                "writer": scope.writer.value,
                "writer_class": spec.writer_class.value,
                "outcome": record.outcome,
                "definition_id": record.definition_id,
                "revision_id": record.revision_id,
                "revision_number": record.revision_number,
                "revision_status": record.revision_status,
                "project_id": record.project_id,
                "checksum": record.checksum,
                "validation_issue_codes": list(record.issue_codes),
            },
        )
    )
