"""The engines a device can run and whose seat it holds, persisted from its handshake so every worker process sees
them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.security.device import DEVICE_STATUS_ACTIVE, UserDevice
from ..agent_gateway.engine_keys import ENGINES

PROFILE_SEAT = "seat"
REPORTED_LISTS = ("seat_engines", "engines")


def note_engines(device: Any, report: Mapping[str, Any]) -> None:
    for key in REPORTED_LISTS:
        if isinstance(report.get(key), list):
            setattr(device, key, sorted({str(engine) for engine in report[key] if engine in ENGINES}))


def runs_engine(device: Any, engine: str) -> bool:
    return engine in list(device.engines or [])


def holds_seat(device: Any, engine: str) -> bool:
    return runs_engine(device, engine) and engine in list(device.seat_engines or [])


async def online_devices(db: AsyncSession, user_id: str) -> list[UserDevice]:
    from .hub import device_hub

    devices = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == user_id, UserDevice.status == DEVICE_STATUS_ACTIVE,
    ).order_by(UserDevice.name))).scalars().all()
    return [device for device in devices if not device.paused and device_hub.reachable(device)]


async def seat_devices(db: AsyncSession, user_id: str, engine: str) -> list[UserDevice]:
    return [device for device in await online_devices(db, user_id) if holds_seat(device, engine)]


__all__ = ["holds_seat", "note_engines", "online_devices", "runs_engine", "seat_devices"]
