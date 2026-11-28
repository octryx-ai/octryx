"""Parallel callers of maintain_policy_runtime run one maintenance, and none of the others waits for it."""

from __future__ import annotations

import asyncio

import pytest

from app.db import core as db_core
from app.services.policy_engine import runtime
from app.services.policy_engine.runtime import PolicyRuntime, maintain_policy_runtime, set_policy_runtime


class _Session:
    opened = 0
    release = asyncio.Event()

    async def __aenter__(self):
        type(self).opened += 1
        await type(self).release.wait()  # the pool has no connection for it yet
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_parallel_callers_open_one_session_and_do_not_wait(monkeypatch):
    _Session.opened, _Session.release = 0, asyncio.Event()
    monkeypatch.setattr(db_core, "async_session_factory", _Session)
    monkeypatch.setattr(runtime, "refresh_policy_runtime", lambda session: asyncio.sleep(0))
    set_policy_runtime(PolicyRuntime())

    first = asyncio.create_task(maintain_policy_runtime())
    await asyncio.sleep(0)
    others = [maintain_policy_runtime() for _ in range(16)]
    await asyncio.wait_for(asyncio.gather(*others), timeout=1)
    assert _Session.opened == 1

    _Session.release.set()
    await asyncio.wait_for(first, timeout=1)
    assert runtime._maintaining is False
