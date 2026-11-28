"""Target ``auto``: device-first with a seat, governed only by rule or as fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ....models.runtime.agent_presence import AgentPresence
from ....models.security.device import DEVICE_STATUS_ACTIVE, UserDevice

KIND_AUTO = "auto"
SEAT_EXHAUSTED_PCT = 99.0
PROFILE_SEAT, PROFILE_GOVERNED = "seat", "governed"
_RECENT_RUNS = 50


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


async def seat_exhausted(db: AsyncSession, user_id: str) -> bool:
    row = (await db.execute(select(AgentPresence).where(
        AgentPresence.user_id == user_id, AgentPresence.profile == PROFILE_SEAT,
        AgentPresence.allowance_updated_at.is_not(None),
    ).order_by(AgentPresence.allowance_updated_at.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return False
    now = datetime.now(UTC)
    if row.allowance_status == "rejected":
        return True
    for pct, resets_at in ((row.five_hour_pct, row.five_hour_resets_at), (row.seven_day_pct, row.seven_day_resets_at)):
        reset = _aware(resets_at)
        if pct is not None and pct >= SEAT_EXHAUSTED_PCT and (reset is None or reset > now):
            return True
    return False


async def _known_folders(db: AsyncSession, user_id: str, repository: str | None) -> dict[str, str]:
    from .target import KIND_DEVICE, stored_target

    if not repository:
        return {}
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.requested_by == user_id, WorkflowRun.repository == repository,
    ).order_by(WorkflowRun.created_at.desc()).limit(_RECENT_RUNS))).scalars().all()
    folders: dict[str, str] = {}
    for target in map(stored_target, rows):
        if target and target["kind"] == KIND_DEVICE and target.get("device_id") and target.get("folder"):
            folders.setdefault(str(target["device_id"]), str(target["folder"]))
    return folders


async def _usable_devices(db: AsyncSession, user: User, folders: dict[str, str]) -> list[tuple[UserDevice, str]]:
    from ...devices.dispatch_gate import folder_allowlisted
    from ...devices.hub import device_hub
    from ...devices.jobs import counted_job_count

    devices = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == user.id, UserDevice.status == DEVICE_STATUS_ACTIVE,
    ).order_by(UserDevice.name))).scalars().all()
    usable: list[tuple[UserDevice, str]] = []
    for device in devices:
        folder = folders.get(device.id)
        if (not folder or device.paused or not device_hub.reachable(device)
                or not folder_allowlisted(folder, list(device.folders or []))):
            continue
        if await counted_job_count(db, device.id) >= int(device.max_parallel_jobs or 1):
            continue
        usable.append((device, folder))
    return usable


async def _allowed(db: AsyncSession, user: User, device: UserDevice, project_id: str | None, profile: str) -> bool:
    from ...devices.device_policy import device_run_decision

    if profile not in [str(item) for item in device.profiles or []]:
        return False
    decision = await device_run_decision(db, user_id=user.id, device=device, workspace_id=project_id,
                                         profile=profile, folder_allowlisted=True)
    return bool(decision.allowed)


def _device_target(device: UserDevice, folder: str, profile: str, reason: str) -> dict[str, Any]:
    return {"kind": "device", "device_id": device.id, "folder": folder, "profile": profile, "model": "",
            "device_name": device.name, "resolved_from": KIND_AUTO, "reason": reason}


async def resolve_auto(db: AsyncSession, *, user: User, project_id: str | None,
                       repository: str | None) -> dict[str, Any]:
    from ...agent_gateway.seat_policy import workspace_seat_decision
    from ...devices.device_policy import _codex_engine

    seat = await workspace_seat_decision(db, project_id, codex=await _codex_engine(db, user.id, project_id)) \
        if project_id else None
    usable = await _usable_devices(db, user, await _known_folders(db, user.id, repository))
    if seat is not None and seat.allowed:
        if await seat_exhausted(db, user.id):
            why = "seat allowance used up (99 % or more)"
        elif not usable:
            why = "no device of yours is online and free with a folder known for this repository"
        else:
            for device, folder in usable:
                if await _allowed(db, user, device, project_id, PROFILE_SEAT):
                    return _device_target(device, folder, PROFILE_SEAT, f"seat on {device.name}")
            why = "the seat profile is not allowed on your devices here"
    else:
        reason = (seat.reason if seat is not None else "") or "no Workspace"
        why = f"a rule forbids the seat ({reason})"
    for device, folder in usable:
        if await _allowed(db, user, device, project_id, PROFILE_GOVERNED):
            return _device_target(device, folder, PROFILE_GOVERNED, f"governed on {device.name}: {why}")
    return {"kind": "server", "resolved_from": KIND_AUTO, "reason": f"governed on the Server: {why}"}


__all__ = ["KIND_AUTO", "resolve_auto", "seat_exhausted"]
