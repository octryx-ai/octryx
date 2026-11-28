"""A seat phase on the server runners: the run pauses until its requester takes it over on a device with that seat."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.security.device import UserDevice
from ...devices.runner_pool import POOL_DEVICE_ID
from ...devices.seat_engines import PROFILE_SEAT, seat_devices
from ..states import PAUSE_SEAT_REQUIRED, STATUS_PAUSED, STATUS_RUNNING

ACTION_LABEL = "Take over on your device"
CODE_NO_SEAT_DEVICE = "no_seat_device_online"


def seat_on_pool(target: dict[str, Any] | None) -> bool:
    return bool(target) and target.get("device_id") == POOL_DEVICE_ID and target.get("profile") == PROFILE_SEAT


def seat_paused(run: WorkflowRun) -> bool:
    return run.status == STATUS_PAUSED and run.pause_reason == PAUSE_SEAT_REQUIRED


def engine_name(engine: str) -> str:
    return engine.replace("_", " ").title()


def _message(engine: str, devices: list[UserDevice]) -> str:
    seat = f"a {engine_name(engine)} seat"
    why = f"This run needs {seat}, and the server runners never hold a person's seat."
    if devices:
        names = ", ".join(device.name for device in devices)
        return f"{why} Take it over on your device ({names}), change where it runs, or abort it."
    return (f"No device with {seat} online. {why} Start octryx-claude on a device logged in with {seat}, then take "
            "the run over on it; or change where it runs, or abort it.")


async def pause_for_seat(db: AsyncSession, run: WorkflowRun) -> Any:
    from ...devices.chat_turn import DeviceTurnRefusal
    from ...session.handovers import open_seat_entry
    from ..limits import pause_run
    from ..review.choice import run_engine

    if run.status == STATUS_RUNNING:
        engine = await run_engine(db, run)
        devices = await seat_devices(db, str(run.requested_by), engine)
        await pause_run(db, run, reason=PAUSE_SEAT_REQUIRED, actor_id=None, detail={
            "code": PAUSE_SEAT_REQUIRED if devices else CODE_NO_SEAT_DEVICE, "engine": engine,
            "devices": [device.name for device in devices], "message": _message(engine, devices),
            "resume": {"kind": "restart", "node_id": run.current_node_id}})
        await open_seat_entry(db, run, {"engine": engine, "profile": PROFILE_SEAT})
    return DeviceTurnRefusal(state="needs_configuration", reason=PAUSE_SEAT_REQUIRED, status=409)


async def lift_seat_pause(db: AsyncSession, run: WorkflowRun, *, actor_id: str) -> None:
    from ...session.handovers import close_run_entries
    from ..pause import record_decision

    record_decision(db, run, kind="pause", subject=PAUSE_SEAT_REQUIRED, action="change_runtime", payload={},
                    user_id=actor_id)
    run.status, run.pause_reason = STATUS_RUNNING, None
    run.node_state = {key: value for key, value in dict(run.node_state or {}).items() if key != "pause"}
    await close_run_entries(db, run, user_id=actor_id)


async def takeover_default(db: AsyncSession, run: WorkflowRun, options: list[dict[str, Any]]) -> str | None:
    from ..review.choice import run_engine
    from .auto import _known_folders

    engine = await run_engine(db, run)
    eligible = {device.id for device in await seat_devices(db, str(run.requested_by), engine)}
    known = await _known_folders(db, str(run.requested_by), run.repository)
    seat_options = [option for option in options if option["target"].get("profile") == PROFILE_SEAT
                    and option["target"].get("device_id") in eligible]
    preferred = [option for option in seat_options
                 if known.get(option["target"]["device_id"]) == option["target"].get("folder")]
    return next((option["key"] for option in preferred + seat_options), None)


__all__ = ["ACTION_LABEL", "lift_seat_pause", "pause_for_seat", "seat_on_pool", "seat_paused", "takeover_default"]
