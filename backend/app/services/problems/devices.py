"""``device`` problems: devices that cannot serve the chat work sent to them."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import ACTIVE_STATUSES, STATUS_FAILED, STATUS_LOST

from ...models import DeviceJob, UserDevice
from ...models.security.device import DEVICE_STATUS_REVOKED
from .links import TARGET_DEVICE, fix_link
from .model import (
    KIND_DEVICE,
    SEVERITY_ATTENTION,
    SEVERITY_PROBLEM,
    CollectContext,
    Problem,
    scoped_object_id,
    workspace_of,
)

OFFLINE_AFTER = timedelta(minutes=10)
_FAILED = (STATUS_FAILED, STATUS_LOST)


def _flag(condition) -> object:
    return func.sum(case((condition, 1), else_=0))


def _unreachable(device: UserDevice, ctx: CollectContext) -> tuple[str, object] | None:
    if device.status == DEVICE_STATUS_REVOKED or device.revoked_at is not None:
        return "revoked", device.revoked_at
    if device.last_seen_at is None or ctx.now - device.last_seen_at > OFFLINE_AFTER:
        return "offline", device.last_seen_at
    return None


async def collect(db: AsyncSession, ctx: CollectContext) -> list[Problem]:
    job = DeviceJob
    workspace = func.coalesce(job.workspace_id, "")
    rows = (await db.execute(
        select(UserDevice, workspace, _flag(job.status.in_(ACTIVE_STATUSES)), _flag(job.status.in_(_FAILED)),
               func.min(job.updated_at), func.max(job.updated_at))
        .join(UserDevice, UserDevice.id == job.device_id)
        .where(job.updated_at >= ctx.window_start, job.status.in_((*ACTIVE_STATUSES, *_FAILED)),
               ctx.scope(workspace))
        .group_by(UserDevice.id, workspace)
        .order_by(func.max(job.updated_at).desc()).limit(ctx.limit)
    )).all()
    problems = []
    for device, workspace_id, waiting, failed, first, last in rows:
        workspace_id = workspace_of(workspace_id)
        common = {"kind": KIND_DEVICE, "object_type": "device", "object_id": device.id, "object_name": device.name,
                  "key_object_id": scoped_object_id(device.id, workspace_id), "workspace_id": workspace_id,
                  "fix": fix_link(TARGET_DEVICE, workspace_id=workspace_id, object_id=device.id)}
        unreachable = _unreachable(device, ctx) if waiting else None
        if unreachable is not None:
            reason, since = unreachable
            state = "was revoked" if reason == "revoked" else "is offline"
            problems.append(Problem(
                **common, severity=SEVERITY_PROBLEM, reason_code=reason, count=int(waiting),
                title=f"Device {device.name} {state} while chat work waits for it.",
                since=since or first, last_seen=last,
            ))
        if failed:
            jobs = "job" if failed == 1 else "jobs"
            problems.append(Problem(
                **common, severity=SEVERITY_ATTENTION, reason_code="jobs_failed", count=int(failed),
                title=f"Device {device.name}: {int(failed)} {jobs} failed in the last 7 days.",
                since=first, last_seen=last,
            ))
    return problems


__all__ = ["OFFLINE_AFTER", "collect"]
