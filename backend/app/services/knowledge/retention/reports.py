"""The read side an operator surface may show: counts, finding ids, sizes and ages. Never a key, content address,
bucket, endpoint or server text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_object_retention import (
    KnowledgeObjectReconciliationFinding,
    KnowledgeObjectReconciliationRun,
)
from .errors import InvalidRetentionRequestError
from .reconcile_record import FindingRecord

DEFAULT_REPORT_FINDINGS = 50
MAX_REPORT_FINDINGS = 200


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: str
    project_id: str
    state: str
    failure: str | None
    mode: str
    min_object_age_hours: int
    inventory_object_count: int
    referenced_object_count: int
    unreferenced_object_count: int
    unrecognized_object_count: int
    candidate_object_count: int
    unreferenced_byte_size: int
    inventory_truncated: bool
    requested_by: str
    started_at: datetime
    finished_at: datetime | None
    findings: tuple[FindingRecord, ...]
    findings_truncated: bool


async def latest_run_report(
    db: AsyncSession, project_id: str, *, limit: int = DEFAULT_REPORT_FINDINGS
) -> RunReport | None:
    if type(project_id) is not str or not project_id:
        raise InvalidRetentionRequestError()
    if type(limit) is not int or not 0 < limit <= MAX_REPORT_FINDINGS:
        raise InvalidRetentionRequestError()
    run = (
        await db.execute(
            select(KnowledgeObjectReconciliationRun)
            .where(KnowledgeObjectReconciliationRun.project_id == project_id)
            .order_by(KnowledgeObjectReconciliationRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    rows = await _run_findings(db, project_id, run.id, limit)
    findings = tuple(
        FindingRecord(
            finding_id=str(row.id),
            byte_size=int(row.byte_size),
            observed_age_hours=int(row.observed_age_hours),
            age_eligible=bool(row.age_eligible),
            state=str(row.state),
        )
        for row in rows[:limit]
    )
    return _run_report(run, project_id, findings, findings_truncated=len(rows) > limit)


async def _run_findings(
    db: AsyncSession, project_id: str, run_id: object, limit: int
) -> list[KnowledgeObjectReconciliationFinding]:
    return (
        (
            await db.execute(
                select(KnowledgeObjectReconciliationFinding)
                .where(
                    KnowledgeObjectReconciliationFinding.project_id == project_id,
                    KnowledgeObjectReconciliationFinding.run_id == run_id,
                )
                # Oldest object first: the same review order the run recorded them in. One
                # row more than the bound is read so truncation is reported, not guessed.
                .order_by(KnowledgeObjectReconciliationFinding.object_last_modified)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )


def _run_report(
    run: KnowledgeObjectReconciliationRun,
    project_id: str,
    findings: tuple[FindingRecord, ...],
    *,
    findings_truncated: bool,
) -> RunReport:
    return RunReport(
        run_id=str(run.id),
        project_id=project_id,
        state=str(run.state),
        failure=str(run.failure) if run.failure is not None else None,
        mode=str(run.mode),
        min_object_age_hours=int(run.min_object_age_hours),
        inventory_object_count=int(run.inventory_object_count),
        referenced_object_count=int(run.referenced_object_count),
        unreferenced_object_count=int(run.unreferenced_object_count),
        unrecognized_object_count=int(run.unrecognized_object_count),
        candidate_object_count=int(run.candidate_object_count),
        unreferenced_byte_size=int(run.unreferenced_byte_size),
        inventory_truncated=bool(run.inventory_truncated),
        requested_by=str(run.requested_by),
        started_at=run.started_at,
        finished_at=run.finished_at,
        findings=findings,
        findings_truncated=findings_truncated,
    )
