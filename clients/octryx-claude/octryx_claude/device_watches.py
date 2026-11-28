"""The device service's background watches: a served update while no job runs, the idle local decision model and
the healthy start after an update (``device_runtime``)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from . import self_update

UPDATE_INTERVAL_SECONDS = 5 * 60
IDLE_POLL_SECONDS = 5.0


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


async def update_watch(manager: Any, stop: asyncio.Event, *, check: Callable[[], self_update.Updated | None],
                       interval: float = UPDATE_INTERVAL_SECONDS,
                       idle_poll: float = IDLE_POLL_SECONDS) -> self_update.Updated | None:
    logger = logging.getLogger("octryx_claude.device")
    while not stop.is_set():
        await _wait(stop, interval)
        if stop.is_set() or manager.turns:
            continue
        updated = await asyncio.to_thread(check)
        if updated is None:
            continue
        logger.info("update %s -> %s activated; restarting once no job runs", updated.previous, updated.version)
        while manager.turns and not stop.is_set():
            await _wait(stop, idle_poll)
        manager.draining = True
        stop.set()
        return updated
    return None


async def local_model_watch(manager: Any, stop: asyncio.Event, *, interval: float = 60.0) -> None:
    while not stop.is_set():
        with contextlib.suppress(Exception):
            await manager.stop_local_model(only_idle=True)
        await _wait(stop, interval)


async def health_watch(client: Any, stop: asyncio.Event, confirm: Callable[[], None], *,
                       grace: float = self_update.HEALTHY_AFTER_SECONDS, poll: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    while not stop.is_set() and not client.connected and loop.time() - started < grace:
        await _wait(stop, poll)
    if stop.is_set() and not client.connected:
        return
    with contextlib.suppress(Exception):
        confirm()

