"""An open chat shows a turn the platform offered at once, like a typed device message (after commit)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

_OFFERED_KEY = "workflow_continuation_offered"


async def _offered_after_commit(db: AsyncSession, job_id: str) -> None:
    from app.services.devices.job_state import serialize_job

    from ....models import DeviceJob

    job = await db.get(DeviceJob, job_id)
    sync = db.sync_session
    sync.info.setdefault(_OFFERED_KEY, []).append(
        (job.session_id, {"job": serialize_job(job), "eventType": "turn_offered"}))
    if not event.contains(sync, "after_commit", _publish_offered):
        event.listen(sync, "after_commit", _publish_offered)
        event.listen(sync, "after_rollback", _drop_offered)


def _publish_offered(session: Any) -> None:
    import asyncio

    from ...devices.jobs_channel import EVENT_TYPE
    from ...session.stream import session_stream_manager

    for session_id, payload in session.info.pop(_OFFERED_KEY, []):
        try:
            asyncio.get_running_loop().create_task(session_stream_manager.publish(session_id, EVENT_TYPE, payload))
        except RuntimeError:  # no running loop (a sync caller): the chat sees the turn once the job is accepted
            return


def _drop_offered(session: Any) -> None:
    session.info.pop(_OFFERED_KEY, None)
