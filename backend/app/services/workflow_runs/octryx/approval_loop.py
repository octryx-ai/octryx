"""A device phase turn that keeps asking for approvals nobody gives pauses its run."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DeviceJob, DeviceJobApproval
from ..states import PAUSE_APPROVAL_TIMEOUT, STATUS_RUNNING

MAX_REFUSED_APPROVALS = 3
REFUSED_STATUSES = ("denied", "expired")
CODE = "device_approvals_unanswered"


async def approval_requested(db: AsyncSession, job: DeviceJob) -> bool:
    from ...devices.jobs import request_stop
    from ..limits import pause_run
    from ..records import WorkflowRunError, active_run_for_session, lock_run
    from .continuation_marker import CONTEXT_KEY, STATE_STARTED

    run = await active_run_for_session(db, job.session_id)
    marker = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}) if run is not None else {}
    if (run is None or run.status != STATUS_RUNNING or marker.get("state") != STATE_STARTED
            or marker.get("job_id") != job.id or not marker.get("started_at")
            or (marker.get("node_id"), marker.get("entry")) != (run.current_node_id,
                                                                dict(run.node_state or {}).get("entry"))):
        return False
    since = datetime.fromisoformat(str(marker["started_at"])).replace(tzinfo=None)
    refused = int((await db.execute(select(func.count()).select_from(DeviceJobApproval).where(
        DeviceJobApproval.job_id == job.id, DeviceJobApproval.status.in_(REFUSED_STATUSES),
        DeviceJobApproval.created_at >= since))).scalar_one())
    if refused < MAX_REFUSED_APPROVALS:
        return False
    try:
        run = await lock_run(db, run)
    except WorkflowRunError:
        return False
    if run.status != STATUS_RUNNING:
        return False
    context = dict(run.context or {})
    context.pop(CONTEXT_KEY, None)
    run.context = context
    if job.status in ("offered", "running"):
        await request_stop(db, job, actor_id=job.owner_user_id)
    await pause_run(db, run, reason=PAUSE_APPROVAL_TIMEOUT, actor_id=None, detail={
        "message": (f"The device asked for approval again after {refused} approvals of this phase were denied or "
                    "expired with nobody answering. Pre-allow what the phase needs, then Continue to run it again, "
                    "or abort the run."),
        "code": CODE, "refused_approvals": refused, "resume": {"kind": "restart", "node_id": run.current_node_id},
    })
    return True


__all__ = ["CODE", "MAX_REFUSED_APPROVALS", "approval_requested"]
