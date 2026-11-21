"""A switch waits for a healthy start, rolls back a failing version and never flip-flops between builds."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from octryx_claude import device_runtime, self_update, self_update_commands, self_update_state
from tests.self_update_support import NEW, OLD, Builder, Platform, _release, _update, installed  # noqa: F401

# --- start health, rollback, no flip-flop --------------------------------------------


def _layout(installed) -> self_update.Layout:  # noqa: F811
    return self_update.detect_layout(installed["state"], prefix=installed["prefix"], home=installed["home"])


def test_the_new_venv_must_import_the_device_service_before_the_switch(installed):  # noqa: F811
    probe = self_update_commands.venv_version_command(Path("/v"))
    assert "octryx_claude.device_runtime" in probe[-1] and "octryx_claude.device_channel" in probe[-1]


def test_a_switch_waits_for_a_healthy_start_and_a_healthy_start_clears_it(installed):  # noqa: F811
    assert _update(installed, Platform(_release())).version == NEW
    layout = _layout(installed)
    pending = installed["venvs"] / self_update_state.PENDING_NAME
    assert pending.exists()
    assert self_update_state.start_attempt(installed["state"], layout, NEW) == ""
    self_update_state.confirm_healthy(layout, NEW)
    assert not pending.exists()
    for _ in range(self_update_state.MAX_START_ATTEMPTS + 1):
        # nothing pending: never rolls back
        assert self_update_state.start_attempt(installed["state"], layout, NEW) == ""
    assert os.readlink(installed["venvs"] / "current") == NEW


def test_failed_start_rolls_back_after_three_attempts(installed):  # noqa: F811
    assert _update(installed, Platform(_release())).version == NEW
    layout = _layout(installed)
    for _ in range(self_update_state.MAX_START_ATTEMPTS):
        assert self_update_state.start_attempt(installed["state"], layout, NEW, now=1_000_100.0) == ""
    assert self_update_state.start_attempt(installed["state"], layout, NEW, now=1_000_100.0) == OLD
    assert os.readlink(installed["venvs"] / "current") == OLD
    assert not (installed["venvs"] / self_update_state.PENDING_NAME).exists()
    # The rolled-back version is not activated again on the next checks (no crash loop of updates).
    platform, builder = Platform(_release()), Builder()
    assert _update(installed, platform, builder=builder, now=1_000_000.0 + 2 * self_update_state.FAILED_RETRY_SECONDS) \
        is None
    assert builder.argv == []
    later = 1_000_100.0 + self_update_state.ROLLED_BACK_RETRY_SECONDS + 1
    assert _update(installed, platform, builder=builder, now=later).version == NEW


def test_alternating_served_builds_do_not_flip_flop(installed):  # noqa: F811
    assert _update(installed, Platform(_release())).version == NEW  # OLD -> NEW at 1_000_000
    back = Platform(_release(OLD))
    updated = self_update.update_if_available(
        installed["state"], warn=[].append, http=back.http, runner=Builder(), env={}, now=1_000_000.0 + 300,
        installed=NEW, prefix=installed["prefix"], home=installed["home"])
    assert updated is None  # the build it just left is not taken back five minutes later
    assert os.readlink(installed["venvs"] / "current") == NEW
    updated = self_update.update_if_available(
        installed["state"], warn=[].append, http=back.http, runner=Builder(), env={},
        now=1_000_000.0 + self_update_state.FLIP_FLOP_SECONDS + 1, installed=NEW, prefix=installed["prefix"],
        home=installed["home"])
    assert updated is not None and updated.version == OLD  # a deliberate downgrade still happens


def test_device_run_rolls_back_a_version_that_keeps_failing_to_start(state, installed, monkeypatch):  # noqa: F811
    from octryx_claude import device_state

    monkeypatch.setattr(device_state, "load_device", lambda _state: {"device_id": "dev_1"})
    layout = _layout(installed)
    monkeypatch.setattr(self_update, "detect_layout", lambda _state, **_kwargs: layout)
    monkeypatch.setattr(device_runtime, "installed_version", lambda: NEW)
    assert _update(installed, Platform(_release())).version == NEW
    pending = installed["venvs"] / self_update_state.PENDING_NAME
    attempts = f'"attempts": {self_update_state.MAX_START_ATTEMPTS}'
    pending.write_text(pending.read_text().replace('"attempts": 0', attempts))
    served: list[str] = []
    restarts: list[tuple] = []

    async def serve(_state, _stop):
        served.append("serve")

    monkeypatch.setattr(device_runtime, "serve", serve)
    monkeypatch.setattr(self_update, "restart", lambda argv, updated, err: restarts.append((argv, updated.version)))
    assert device_runtime.run_service(state) == device_runtime.EXIT_RESTART_FOR_UPDATE
    assert served == [] and restarts == [(("device", "run"), OLD)]
    assert os.readlink(installed["venvs"] / "current") == OLD


@pytest.mark.asyncio
async def test_health_watch_confirms_once_connected_or_after_the_grace():
    class Client:
        connected = False

    confirmed: list[str] = []
    client, stop = Client(), asyncio.Event()
    watch = asyncio.create_task(device_runtime.health_watch(client, stop, lambda: confirmed.append("ok"),
                                                            grace=60, poll=0.01))
    await asyncio.sleep(0.05)
    assert confirmed == []
    client.connected = True
    await asyncio.wait_for(watch, 1)
    assert confirmed == ["ok"]
    await asyncio.wait_for(device_runtime.health_watch(Client(), stop, lambda: confirmed.append("grace"),
                                                       grace=0.05, poll=0.01), 1)
    assert confirmed == ["ok", "grace"]
