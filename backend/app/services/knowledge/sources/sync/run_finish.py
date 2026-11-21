"""The end of a Source Sync run: retiring what a completed pass no longer listed, recording the run, audit."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .....models import AuditLog
from .....models.project.knowledge_source_sync import (
    RUN_STATE_COMPLETED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
)
from .....time_utils import utc_now
from ...structured.build import refresh_after_sync
from .contract import REASON_REMOVED_AT_SOURCE
from .items import ConnectorRef, retire_item, served_items_unseen_in
from .run_report import RunReport, current_withheld

# The runner's logger, so the run's log lines keep their origin.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".runner")

RUN_AUDIT_ACTION = "knowledge.connector.run"


async def _reconcile(db: AsyncSession, ref: ConnectorRef, pass_number: int, report: RunReport) -> None:
    """The pass completed: every served item it did not list is gone at the source."""
    for state in await served_items_unseen_in(db, ref, pass_number):
        external_id = state.external_id
        await retire_item(db, state, withheld=False, outcome=REASON_REMOVED_AT_SOURCE)
        report.record(external_id, "retired", reason=REASON_REMOVED_AT_SOURCE)
    await db.commit()


async def _finish(
    db: AsyncSession,
    ref: ConnectorRef,
    run_id: str,
    state: str,
    reason: str | None,
    report: RunReport,
    actor_id: str | None,
) -> None:
    report.withheld_current = await current_withheld(db, ref)
    run = await db.get(KnowledgeSourceSyncRun, run_id)
    run.state = state
    run.reason = reason
    # Completed, but some items failed: never shown as a clean run.
    run.report = report.as_dict() | {
        "completed_with_failures": state == RUN_STATE_COMPLETED and report.counts["failed"] > 0
    }
    run.outcomes = report.outcomes
    run.finished_at = utc_now()
    row = await db.get(KnowledgeSourceConnector, ref.id)
    row.last_run_id = run_id
    row.run_lease_until = None
    db.add(
        AuditLog(
            user_id=actor_id,
            action=RUN_AUDIT_ACTION,
            resource_type="knowledge_source_connector",
            resource_id=ref.id,
            details={
                "workspace_id": ref.project_id,
                "run_id": run_id,
                "state": state,
                "reason": reason,
                **report.counts,
            },
        )
    )
    await db.commit()
    if any(report.counts[key] for key in ("created", "updated", "retired")):
        # The structured graph of a Workspace that has one follows its sources.
        await refresh_after_sync(db, ref.project_id, ref.kind)
    logger.info(
        "Knowledge source sync run finished: state=%s reason=%s counts=%s workspace=%s",
        state,
        reason,
        report.counts,
        ref.project_id,
    )
