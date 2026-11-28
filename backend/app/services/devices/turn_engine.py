"""A turn goes only to a device that reported its engine at the handshake: never a job that fails on the device."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, UserDevice
from .contract import STATE_NEEDS_CONFIGURATION
from .job_engine import job_engine
from .job_state import DeviceJobError
from .seat_engines import runs_engine

REASON_DEVICE_ENGINE_MISSING = "device_engine_missing"


async def require_engine(db: AsyncSession, device: UserDevice, job: DeviceJob) -> None:
    if not runs_engine(device, await job_engine(db, job)):
        raise DeviceJobError(REASON_DEVICE_ENGINE_MISSING, 409, STATE_NEEDS_CONFIGURATION)


__all__ = ["REASON_DEVICE_ENGINE_MISSING", "require_engine"]
