"""The sandbox runner's serving loop (``sandbox``): the channel and the job manager without the person-level parts,
the device report of a sandbox and its idle end."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from . import __version__, device_state
from .state import LocalState

IDLE_EXIT_SECONDS = 600.0
FIRST_JOB_SECONDS = 900.0


def report(state: LocalState) -> dict[str, Any]:
    device = device_state.load_device(state)
    return {"folders": list(device.get("folders") or []), "profiles_available": ["governed"], "max_parallel_jobs": 1,
            "paused": False, "seat_login": False, "client_version": __version__, "service_kind": "sandbox",
            "live": False}


async def idle_watch(manager: Any, stop: asyncio.Event, *, clock: Callable[[], float] = time.monotonic,
                     idle_exit: float = IDLE_EXIT_SECONDS, first_job: float = FIRST_JOB_SECONDS,
                     poll: float = 5.0) -> str:
    """Ends the sandbox: idle for ``idle_exit`` after a turn ran, or no job at all within ``first_job``."""
    started = last_busy = clock()
    worked = False
    while not stop.is_set():
        now = clock()
        if manager.turns:
            worked, last_busy = True, now
        elif worked and now - last_busy >= idle_exit:
            stop.set()
            return "idle"
        elif not worked and now - started >= first_job:
            stop.set()
            return "no_job"
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), poll)
    return "stopped"


async def serve(state: LocalState, stop: asyncio.Event) -> str:
    """The channel and the job manager until ``stop``, the idle end or a revoke."""
    from .device_channel import ChannelClient  # noqa: PLC0415
    from .device_channel_auth import (
        channel_token,
        revocation_check,  # noqa: PLC0415
    )
    from .device_jobs import JobManager  # noqa: PLC0415

    manager = JobManager(state)

    async def on_message(message_type: str, body: dict[str, Any]) -> None:
        if not message_type.startswith("live_"):  # a sandbox has no live sessions
            await manager.handle(message_type, body)

    client = ChannelClient(state, token_provider=lambda force: channel_token(state, force),
                           report=lambda: report(state), on_message=on_message,
                           confirm_revoked=lambda: revocation_check(state),
                           recheck_revoked=lambda: revocation_check(state, recheck=True))
    manager.attach(client)
    idle = asyncio.create_task(idle_watch(manager, stop))
    try:
        await client.run_forever(stop)
    finally:
        stop.set()
        await manager.stop_all("sandbox_stopped")
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await idle
    return idle.result() if idle.done() and not idle.cancelled() else "stopped"
