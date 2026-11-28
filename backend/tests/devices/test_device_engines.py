from __future__ import annotations

import pytest

from app.models import UserDevice
from app.services.session.handover_pool import can_run_now
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run, _hub, _jobs  # noqa: F401

GOVERNED_CLAUDE = {"engine": "claude_code", "profile": "governed"}


@pytest.mark.asyncio
async def test_a_turn_never_goes_to_a_device_without_its_engine_and_leaves_no_job(db):
    admin, device, thread, run = await _device_run(db)
    (await db.get(UserDevice, device.id)).engines = ["codex"]
    await _confirm(db, run, admin)
    assert await _jobs(db, thread) == []
    waiting = dict(run.node_state or {}).get("waiting") or {}
    assert (run.status, waiting.get("reason")) == ("waiting", "device_engine_missing")


@pytest.mark.asyncio
async def test_a_device_that_never_reported_its_engines_runs_nothing(db):
    admin, device, thread, run = await _device_run(db)
    (await db.get(UserDevice, device.id)).engines = None
    await _confirm(db, run, admin)
    assert await _jobs(db, thread) == []


@pytest.mark.asyncio
async def test_a_pool_entry_is_runnable_only_on_a_device_with_its_engine(db):
    admin, device, _thread, _run = await _device_run(db)
    assert await can_run_now(db, admin, GOVERNED_CLAUDE, None)
    (await db.get(UserDevice, device.id)).engines = ["codex"]
    assert not await can_run_now(db, admin, GOVERNED_CLAUDE, None)
