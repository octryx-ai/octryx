"""The devices, seats and the day's cost of Operations › Live."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_state import ACTIVE_STATUSES

from ...models import AgentPresence, DeviceJob, Session, UsageEvent, User, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ..problems.model import iso
from .runs import person

RECENT = timedelta(hours=24)


def served_version() -> str | None:
    from ..octryx_client.artifact import ClientArtifactError, current_artifact

    try:
        return current_artifact().version
    except (ClientArtifactError, OSError):
        return None


# The served client is ``<__version__>+<source hash>`` (``0.2.0+1a2b3c4d5e6f``); devices report the same form or a
# plain release. Compared here without ``packaging``, which the backend does not declare.
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-.]?(dev|a|alpha|b|beta|rc)\.?(\d*))?(?:\+([0-9A-Za-z.]+))?$")
_PRE_RANK = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3}
_FINAL = (4, 0)


def _version_key(text: str) -> tuple[tuple[int, ...], tuple[int, int], str] | None:
    match = _VERSION.match(text.strip())
    if match is None:
        return None
    release, pre, pre_number, local = match.groups()
    numbers = [int(part) for part in release.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    rank = _FINAL if pre is None else (_PRE_RANK[pre.lower()], int(pre_number or 0))
    return tuple(numbers), rank, local or ""


def _outdated(client: str | None, served: str | None) -> bool:
    if not client or not served:
        return False
    client_key, served_key = _version_key(client), _version_key(served)
    if client_key is None or served_key is None:
        return client != served
    if client_key[:2] != served_key[:2]:
        return client_key[:2] < served_key[:2]
    # Same release, different source hash: the served build is the current one, so the device is behind.
    return client_key[2] != served_key[2]


async def devices(db: AsyncSession, *, viewer_id: str, scope: Any, platform_wide: bool,
                  now: datetime) -> list[dict[str, Any]]:
    workspace = func.coalesce(DeviceJob.workspace_id, "")
    used = select(DeviceJob.device_id).where(DeviceJob.updated_at >= now - RECENT, scope(workspace))
    query = select(UserDevice).where(UserDevice.status == DEVICE_STATUS_ACTIVE)
    if not platform_wide:
        query = query.where(UserDevice.id.in_(used))
    rows = list((await db.execute(query.order_by(UserDevice.name))).scalars())
    if not rows:
        return []
    ids = [device.id for device in rows]
    running = dict((await db.execute(
        select(DeviceJob.device_id, func.count()).where(DeviceJob.device_id.in_(ids),
                                                        DeviceJob.status.in_(ACTIVE_STATUSES), scope(workspace))
        .group_by(DeviceJob.device_id))).all())
    owners = {user.id: user for user in (await db.execute(
        select(User).where(User.id.in_({device.owner_user_id for device in rows})))).scalars()}
    from ..devices.hub import device_hub

    served = served_version()
    return [{
        "id": device.id, "name": device.name, "owner": person(owners.get(device.owner_user_id), viewer_id),
        "online": device_hub.connected(device.id), "last_seen_at": iso(device.last_seen_at),
        "client_version": device.client_version, "served_version": served,
        "outdated": _outdated(device.client_version, served), "paused": bool(device.paused),
        "jobs_running": int(running.get(device.id, 0)), "max_parallel_jobs": device.max_parallel_jobs,
    } for device in rows]


async def seats(db: AsyncSession, *, viewer_id: str, scope: Any, now: datetime) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(AgentPresence, User).join(User, User.id == AgentPresence.user_id)
        .where(AgentPresence.last_seen_at >= now - RECENT, AgentPresence.five_hour_pct.is_not(None),
               scope(AgentPresence.project_id))
        .order_by(AgentPresence.allowance_updated_at.desc().nulls_last(), AgentPresence.last_seen_at.desc())
    )).all()
    newest: dict[str, dict[str, Any]] = {}
    for presence, user in rows:
        newest.setdefault(user.id, {
            "user": person(user, viewer_id), "five_hour_pct": presence.five_hour_pct,
            "five_hour_resets_at": iso(presence.five_hour_resets_at), "seven_day_pct": presence.seven_day_pct,
            "seven_day_resets_at": iso(presence.seven_day_resets_at),
            "updated_at": iso(presence.allowance_updated_at or presence.last_seen_at),
        })
    return sorted(newest.values(), key=lambda row: -(row["five_hour_pct"] or 0))


async def cost_24h(db: AsyncSession, *, scope: Any, now: datetime) -> dict[str, float]:
    api, equivalent = (await db.execute(
        select(func.coalesce(func.sum(UsageEvent.cost), 0), func.coalesce(func.sum(UsageEvent.list_cost), 0))
        .join(Session, Session.id == UsageEvent.session_id)
        .where(UsageEvent.created_at >= now - RECENT, scope(func.coalesce(Session.project_id, ""))))).one()
    return {"cost_24h_usd": round(float(api or 0), 6), "seat_api_equivalent_24h_usd": round(float(equivalent or 0), 6)}


__all__ = ["RECENT", "cost_24h", "devices", "seats", "served_version"]
