"""Refresh a recorded pull request from its host (status, reviewers, build, timestamps).

Internal only (no HTTP route): the periodic worker (``refresh_worker``: open PRs not read for ``REFRESH_INTERVAL``,
plus every row a trigger requested) and a workflow watch that observed the PR merged or declined
(``request_refresh_for_run``: marks the row, the worker reads it on its next tick, outside the run's claim).

A successful read stores the host's state (``refresh_status = ok``, ``last_synced_at`` now); a read whose build
status could not be read stores the rest and says so (``partial`` + the build error's code). A failed read never
touches the recorded state: the last known status stays, ``refresh_status = failed`` with the closed error code and
a bounded message (``host_target.PullRequestHostError``).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, WorkflowRun, WorkItem, WorkPullRequest
from ....time_utils import utc_now
from .host_clients import HostRead, client_for, host_name
from .host_state import HostStateError
from .host_target import SUPPORTED_PROVIDERS, PullRequestHostError, host_error, resolve_target
from .pull_requests import detect_mismatches, find_record, recorded_profile
from .record_identity import in_item_workspace, stored_identity

logger = logging.getLogger(__name__)

REFRESH_OK, REFRESH_PARTIAL, REFRESH_FAILED = "ok", "partial", "failed"
REFRESH_INTERVAL = timedelta(minutes=15)
SWEEP_BATCH = 25
REFRESHABLE_OPEN_STATUSES = ("open", "opened", "active", "in_review", "review")
SOURCE_PERIODIC, SOURCE_REQUESTED = "periodic", "requested"
SYSTEM_ACTOR = "system:pull_request_refresh"


async def _read(db: AsyncSession, row: WorkPullRequest) -> tuple[HostRead, str]:
    target = await resolve_target(db, row)
    try:
        return await client_for(target).read(target), target.connection_id
    except HostStateError as error:
        raise PullRequestHostError(error.code, error.message) from None
    except Exception as error:
        raise host_error(error, host_name(target)) from None


def _apply(row: WorkPullRequest, read: HostRead, connection_id: str) -> None:
    pr = read.pull_request
    row.status = pr.status
    row.reviewers_json = [dict(item) for item in pr.reviewers]
    row.approvals_json = pr.approvals
    for column, value in (("title", pr.title), ("source_branch", pr.source_branch),
                          ("target_branch", pr.target_branch), ("source_updated_at", pr.source_updated_at)):
        if value:
            setattr(row, column, value)
    if pr.source_created_at and not row.source_created_at:
        row.source_created_at = pr.source_created_at
    if pr.author:
        row.author_json = dict(pr.author)
    if read.build_error is None:
        row.build_status = read.build_status
    row.raw_summary_json = {**dict(row.raw_summary_json or {}), "host": {
        "state": pr.host_state, "connection_id": connection_id, "head_commit": pr.head_commit}}
    row.last_synced_at = utc_now()
    error = read.build_error
    row.refresh_status = REFRESH_PARTIAL if error else REFRESH_OK
    row.refresh_error_code = error.code if error else None
    row.refresh_error = error.message if error else None


async def refresh_pull_request(db: AsyncSession, row: WorkPullRequest, *, source: str) -> dict[str, Any]:
    """Read ``row`` from its host and store the outcome; returns ``{"ok", "previous_status", "status", ...}``."""
    previous = row.status
    row.refresh_attempted_at = utc_now()
    row.refresh_requested_at = None
    try:
        read, connection_id = await _read(db, row)
    except PullRequestHostError as error:
        row.refresh_status, row.refresh_error_code, row.refresh_error = REFRESH_FAILED, error.code, error.message
        await db.flush()
        return {"ok": False, "previous_status": previous, "status": row.status, "error_code": error.code,
                "source": source}
    _apply(row, read, connection_id)
    row.mismatch_json = await detect_mismatches(db, row, await recorded_profile(db, row))
    await db.flush()
    if previous != row.status:
        db.add(AuditLog(user_id=row.created_by, action="secure_work.pull_request_refreshed",
                        resource_type="secure_work_pull_request", resource_id=row.id,
                        details={"pr_id": row.pr_id, "repository_slug": row.repository_slug, "provider": row.provider,
                                 "actor": SYSTEM_ACTOR, "source": source, "previous_status": previous,
                                 "status": row.status}))
    return {"ok": True, "previous_status": previous, "status": row.status, "refresh_status": row.refresh_status,
            "source": source}


def due_pull_requests_query(*, now=None, batch: int = SWEEP_BATCH):
    """Rows a trigger requested, then open rows not read for ``REFRESH_INTERVAL`` (never read first); only records
    bound to their Work Item's Workspace (``in_item_workspace``)."""
    now = now or utc_now()
    due_open = (WorkPullRequest.status.in_(REFRESHABLE_OPEN_STATUSES)
                & or_(WorkPullRequest.refresh_attempted_at.is_(None),
                      WorkPullRequest.refresh_attempted_at <= now - REFRESH_INTERVAL))
    return (select(WorkPullRequest.id)
            .where(in_item_workspace(), WorkPullRequest.provider.in_(SUPPORTED_PROVIDERS),
                   or_(WorkPullRequest.refresh_requested_at.is_not(None), due_open))
            .order_by(WorkPullRequest.refresh_requested_at.desc().nullslast(),
                      WorkPullRequest.refresh_attempted_at.asc().nullsfirst())
            .limit(max(1, batch)))


async def sweep_pull_requests(db: AsyncSession, *, batch: int = SWEEP_BATCH) -> dict[str, int]:
    """One bounded pass; each row commits on its own so one slow host never holds another row's write."""
    counts = {"refreshed": 0, "failed": 0}
    for row_id in list((await db.execute(due_pull_requests_query(batch=batch))).scalars().all()):
        row = await db.get(WorkPullRequest, row_id)
        if row is None:
            continue
        source = SOURCE_REQUESTED if row.refresh_requested_at is not None else SOURCE_PERIODIC
        try:
            outcome = await refresh_pull_request(db, row, source=source)
            await db.commit()
        except Exception:
            logger.warning("pull_request.refresh_failed id=%s", row_id, exc_info=True)
            await db.rollback()
            counts["failed"] += 1
            continue
        counts["refreshed" if outcome["ok"] else "failed"] += 1
    return counts


async def request_refresh_for_run(db: AsyncSession, run: WorkflowRun) -> int:
    """A workflow watch observed the run's PR merged/declined: mark its record for the worker's next tick.

    Only the record ``pr_details`` wrote for the run: the run's Work Item in the run's Workspace (``project_id``), the
    identity the run stored when it opened the pull request (``run.pull_request["identity"]``)."""
    identity = stored_identity(run.pull_request)
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None or not run.project_id or item.project_id != run.project_id or identity is None:
        return 0
    row = await find_record(db, scope_key=run.project_id, identity=identity)
    if row is None or row.work_item_id != item.id:
        return 0
    row.refresh_requested_at = utc_now()
    return 1


__all__ = ["REFRESH_FAILED", "REFRESH_INTERVAL", "REFRESH_OK", "REFRESH_PARTIAL", "SWEEP_BATCH",
           "due_pull_requests_query", "refresh_pull_request", "request_refresh_for_run", "sweep_pull_requests"]
