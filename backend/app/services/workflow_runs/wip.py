"""The run's work in progress (``octryx-wip/<run id>``): pushed by the Server from the device's change after each device
turn (``server_wip``), the device's own push (octryx-claude) only as a fallback."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob
from ...time_utils import utc_now

CONTEXT_KEY = "wip"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^octryx-wip/[A-Za-z0-9._-]{1,60}$")


async def record_wip(db: AsyncSession, job: DeviceJob, body: dict[str, Any]) -> None:
    # A failed device push is never an error event: it is only a fallback.
    from .records import active_run_for_session, record_event
    from .server_wip import push_from_device_change

    run = await active_run_for_session(db, job.session_id)
    if run is None:
        return
    result = await push_from_device_change(db, run)
    if result is not None and result["state"] in ("pushed", "unchanged") and _SHA.match(str(result.get("sha") or "")):
        _keep(db, run, result["branch"], result["sha"], job_id=job.id, state=result["state"], by="server")
        return
    branch, sha = str(body.get("branch") or ""), str(body.get("sha") or "")
    if body.get("kind") == "wip_pushed" and _BRANCH.match(branch) and _SHA.match(sha):
        _keep(db, run, branch, sha, job_id=job.id, state=str(body.get("state") or "")[:20], by="device")
        return
    if result is not None:  # the Server's own push failed: that is the run's WIP failure
        record_event(db, run, "wip_failed", node_id=run.current_node_id,
                     detail={"state": "failed", "branch": result["branch"], "sha": "", "by": "server",
                             "reason": str(result.get("reason") or "")[:80], "job_id": job.id})


def _keep(db: AsyncSession, run: Any, branch: str, sha: str, *, job_id: str, state: str, by: str) -> None:
    from .records import record_event

    run.context = {**dict(run.context or {}), CONTEXT_KEY: {"branch": branch, "sha": sha, "at": utc_now().isoformat(),
                                                            "job_id": job_id, "by": by}}
    record_event(db, run, "wip_pushed", node_id=run.current_node_id,
                 detail={"state": state, "branch": branch, "sha": sha, "reason": "", "job_id": job_id, "by": by})


__all__ = ["CONTEXT_KEY", "record_wip"]
