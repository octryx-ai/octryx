"""Shared waiting, revoked-state and fake clock helpers for the device connection stability tests."""

from __future__ import annotations

import asyncio
import time

from octryx_claude import device_state


async def _until(predicate, seconds: float = 2.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.005)


def _revoked_locally(state) -> None:
    device = device_state.load_device(state)
    device["revoked"] = True
    device_state.save_device(state, device)
