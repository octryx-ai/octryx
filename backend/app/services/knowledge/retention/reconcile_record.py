"""The write side of a reconciliation run: its run row, its findings and the supersession of older ones."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_object_retention import (
    FINDING_STATE_OBSERVED,
    FINDING_STATE_SUPERSEDED,
    RUN_STATE_COMPLETED,
    RUN_STATE_FAILED,
    RUN_STATE_LEGAL_HOLD,
    KnowledgeObjectReconciliationFinding,
    KnowledgeObjectReconciliationRun,
)
from ....time_utils import utc_now
from ..identity.workspace import WorkspaceId
from ..objects import InventoryObject
from .governance_lock import lock_workspace_governance
from .policy import RetentionPolicy

# The reconciliation's logger: its records keep the one name operators filter on.
logger = logging.getLogger(__package__ + ".reconcile")


@dataclass(frozen=True, slots=True)
class FindingRecord:
    finding_id: str
    byte_size: int
    observed_age_hours: int
    age_eligible: bool
    state: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    run_id: str
    project_id: str
    mode: str
    min_object_age_hours: int
    inventory_object_count: int
    referenced_object_count: int
    unreferenced_object_count: int
    unrecognized_object_count: int
    candidate_object_count: int
    unreferenced_byte_size: int
    inventory_truncated: bool
    findings: tuple[FindingRecord, ...]


async def _supersede_open_findings(db: AsyncSession, project_id: str) -> None:
    await db.execute(
        update(KnowledgeObjectReconciliationFinding)
        .where(
            KnowledgeObjectReconciliationFinding.project_id == project_id,
            KnowledgeObjectReconciliationFinding.state == FINDING_STATE_OBSERVED,
        )
        .values(state=FINDING_STATE_SUPERSEDED, updated_at=utc_now())
    )


async def _record_failed_run(
    db: AsyncSession,
    *,
    project_id: str,
    policy: RetentionPolicy,
    operator: str,
    started_at: datetime,
    failure: str,
) -> None:
    db.add(
        KnowledgeObjectReconciliationRun(
            id=str(uuid.uuid4()),
            project_id=project_id,
            mode=policy.mode,
            min_object_age_hours=policy.min_object_age_hours,
            state=RUN_STATE_FAILED,
            failure=failure,
            requested_by=operator,
            started_at=started_at,
            finished_at=utc_now(),
        )
    )
    await db.commit()
    logger.warning("Knowledge object reconciliation failed: failure=%s workspace=%s", failure, project_id)


async def _record_legal_hold_run(
    db: AsyncSession, *, project_id: str, policy: RetentionPolicy, operator: str, started_at: datetime
) -> ReconciliationReport:
    await lock_workspace_governance(db, project_id=project_id)
    # Earlier observations are no longer actionable while the Workspace is held.
    await _supersede_open_findings(db, project_id)
    run_id = str(uuid.uuid4())
    db.add(
        KnowledgeObjectReconciliationRun(
            id=run_id,
            project_id=project_id,
            mode=policy.mode,
            min_object_age_hours=policy.min_object_age_hours,
            state=RUN_STATE_LEGAL_HOLD,
            requested_by=operator,
            started_at=started_at,
            finished_at=utc_now(),
        )
    )
    await db.commit()
    logger.info("Knowledge object reconciliation skipped under legal hold: workspace=%s", project_id)
    counts = _RunCounts(inventory=0, unreferenced=0, unrecognized=0, candidates=0, total_bytes=0, truncated=False)
    return _report(run_id, project_id, policy, counts, [])


async def _record_run(
    db: AsyncSession,
    *,
    workspace: WorkspaceId,
    policy: RetentionPolicy,
    operator: str,
    started_at: datetime,
    observed_at: datetime,
    inventory: tuple[InventoryObject, ...],
    referenced: set[str],
    unrecognized: int,
    truncated: bool,
) -> ReconciliationReport:
    project_id = workspace.canonical
    run_id = str(uuid.uuid4())
    # The governance boundary, held until this run and its supersessions are committed, so a
    # policy change of this Workspace never interleaves with them.
    await lock_workspace_governance(db, project_id=project_id)
    unreferenced = [item for item in inventory if item.key not in referenced]
    # Oldest first: the objects whose abandonment is least ambiguous come first, which is
    # also the order an operator reviews them in.
    unreferenced.sort(key=lambda item: (item.last_modified, item.key))
    candidates = 0
    total_bytes = 0
    await _supersede_open_findings(db, project_id)
    for item in unreferenced:
        age_hours = item.age_hours(observed_at)
        candidates += 1 if age_hours >= policy.min_object_age_hours else 0
        total_bytes += item.byte_size
    counts = _RunCounts(
        inventory=len(inventory), unreferenced=len(unreferenced), unrecognized=unrecognized,
        candidates=candidates, total_bytes=total_bytes, truncated=truncated,
    )
    # The run row is inserted, and flushed, before the findings that reference it: PostgreSQL
    # checks ``knowledge_object_reconciliation_findings_run_id_fkey`` per statement, so the
    # obligation's parent has to exist first (the same explicit ordering the ledger makes for
    # its outbox entry). It is an order boundary, not a transaction boundary — the commit
    # below is still the only one, so a crash leaves neither the run nor its findings.
    db.add(_completed_run(run_id, project_id, policy, counts, operator=operator, started_at=started_at))
    await db.flush()
    records = _add_findings(db, unreferenced, run_id=run_id, project_id=project_id, observed_at=observed_at,
                            policy=policy)
    await db.commit()
    logger.info(
        "Knowledge object reconciliation completed: objects=%d unreferenced=%d candidates=%d "
        "truncated=%s workspace=%s",
        counts.inventory,
        counts.unreferenced,
        counts.candidates,
        counts.truncated,
        project_id,
    )
    return _report(run_id, project_id, policy, counts, records)


@dataclass(frozen=True, slots=True)
class _RunCounts:
    inventory: int
    unreferenced: int
    unrecognized: int
    candidates: int
    total_bytes: int
    truncated: bool


def _completed_run(
    run_id: str, project_id: str, policy: RetentionPolicy, counts: _RunCounts, *, operator: str,
    started_at: datetime,
) -> KnowledgeObjectReconciliationRun:
    return KnowledgeObjectReconciliationRun(
        id=run_id,
        project_id=project_id,
        mode=policy.mode,
        min_object_age_hours=policy.min_object_age_hours,
        state=RUN_STATE_COMPLETED,
        inventory_object_count=counts.inventory,
        referenced_object_count=counts.inventory - counts.unreferenced,
        unreferenced_object_count=counts.unreferenced,
        unrecognized_object_count=counts.unrecognized,
        candidate_object_count=counts.candidates,
        unreferenced_byte_size=counts.total_bytes,
        inventory_truncated=counts.truncated,
        requested_by=operator,
        started_at=started_at,
        finished_at=utc_now(),
    )


def _add_findings(
    db: AsyncSession,
    unreferenced: list[InventoryObject],
    *,
    run_id: str,
    project_id: str,
    observed_at: datetime,
    policy: RetentionPolicy,
) -> list[FindingRecord]:
    records: list[FindingRecord] = []
    for item in unreferenced:
        age_hours = item.age_hours(observed_at)
        eligible = age_hours >= policy.min_object_age_hours
        finding_id = str(uuid.uuid4())
        db.add(
            KnowledgeObjectReconciliationFinding(
                id=finding_id,
                run_id=run_id,
                project_id=project_id,
                object_key=item.key,
                content_sha256=item.content_sha256,
                byte_size=item.byte_size,
                object_last_modified=item.last_modified,
                observed_age_hours=age_hours,
                age_eligible=eligible,
                state=FINDING_STATE_OBSERVED,
            )
        )
        records.append(
            FindingRecord(
                finding_id=finding_id,
                byte_size=item.byte_size,
                observed_age_hours=age_hours,
                age_eligible=eligible,
                state=FINDING_STATE_OBSERVED,
            )
        )
    return records


def _report(
    run_id: str, project_id: str, policy: RetentionPolicy, counts: _RunCounts, records: list[FindingRecord]
) -> ReconciliationReport:
    return ReconciliationReport(
        run_id=run_id,
        project_id=project_id,
        mode=policy.mode,
        min_object_age_hours=policy.min_object_age_hours,
        inventory_object_count=counts.inventory,
        referenced_object_count=counts.inventory - counts.unreferenced,
        unreferenced_object_count=counts.unreferenced,
        unrecognized_object_count=counts.unrecognized,
        candidate_object_count=counts.candidates,
        unreferenced_byte_size=counts.total_bytes,
        inventory_truncated=counts.truncated,
        findings=tuple(records),
    )
