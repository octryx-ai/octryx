"""After an update the launcher re-executes, and the device service updates only while idle, then restarts."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from octryx_claude import device_runtime, entry, self_update, self_update_layout, update_check
from octryx_claude.device_jobs import JobManager
from tests.self_update_support import NEW, OLD, Builder, Platform, _release, installed  # noqa: F401

# --- restart and the start step ----------------------------------------------------------------------------------


def _updated(installed) -> self_update.Updated:  # noqa: F811
    return self_update.Updated(OLD, NEW, self_update.Layout(installed["state"].root, installed["home"]))


# --- device service ----------------------------------------------------------------------------------------------


class FakeManager:
    def __init__(self, busy_rounds: int = 0) -> None:
        self.turns = {"job": object()} if busy_rounds else {}
        self.busy_rounds = busy_rounds
        self.draining = False


def test_restart_execs_the_shim_with_the_original_argv(installed):  # noqa: F811
    env, calls, err = {}, [], io.StringIO()
    self_update.restart(["status", "--json"], _updated(installed), err, env=env,
                        execv=lambda path, argv: calls.append((path, argv)))
    shim = str(installed["shim"])
    assert calls == [(shim, [shim, "status", "--json"])]
    assert env[self_update.REEXEC_GUARD_ENV] == NEW
    assert err.getvalue() == f"octryx-claude updated {OLD} -> {NEW}\n"


def test_restart_without_the_installer_shim_uses_current(installed):  # noqa: F811
    installed["shim"].unlink()
    assert _updated(installed).layout.shim == installed["venvs"] / "current" / "bin" / "octryx-claude"


def test_restart_never_execs_the_shim_of_another_installation(installed, tmp_path):  # noqa: F811
    """A second OCTRYX_CLAUDE_HOME must not run through the first installation's shim."""
    installed["shim"].write_text(f"#!/bin/sh\n{self_update_layout.SHIM_MARK}\n"
                                 f"exec '{tmp_path / 'other' / 'venvs' / 'current'}/bin/octryx-claude' \"$@\"\n")
    assert _updated(installed).layout.shim == installed["venvs"] / "current" / "bin" / "octryx-claude"


def test_failed_exec_keeps_running_and_drops_the_guard(installed):  # noqa: F811
    env, err = {}, io.StringIO()

    def refuse(path, argv):
        raise OSError("exec format error")

    self_update.restart(["status"], _updated(installed), err, env=env, execv=refuse)
    assert self_update.REEXEC_GUARD_ENV not in env
    assert "could not restart" in err.getvalue()


def test_on_start_updates_then_re_executes(installed, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(self_update.os, "execv", lambda path, argv: calls.append(argv))
    env = {}
    self_update.on_start(["device", "run"], io.StringIO(), env=env, state=installed["state"],
                         http=Platform(_release()).http, runner=Builder(), now=1_000_000.0, installed=OLD,
                         prefix=installed["prefix"], home=installed["home"])
    assert calls == [[str(installed["shim"]), "device", "run"]]


def test_the_re_executed_process_never_checks_again(installed):  # noqa: F811
    platform, env = Platform(_release()), {self_update.REEXEC_GUARD_ENV: NEW}
    self_update.on_start(["status"], io.StringIO(), env=env, state=installed["state"], http=platform.http,
                         installed=OLD, prefix=installed["prefix"], home=installed["home"])
    assert platform.calls == [] and self_update.REEXEC_GUARD_ENV not in env


def test_opt_out_falls_back_to_the_notice(installed, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(update_check, "notify", lambda out: seen.append("notice"))
    platform = Platform(_release())
    self_update.on_start(["status"], io.StringIO(), env={self_update.AUTO_UPDATE_ENV: "off"},
                         state=installed["state"], http=platform.http)
    assert seen == ["notice"] and platform.calls == []


def test_on_start_never_raises(monkeypatch):
    monkeypatch.setattr(self_update, "update_if_available", lambda **_: 1 / 0)
    self_update.on_start(["status"], io.StringIO(), env={})


def test_entry_runs_the_start_step_only_for_person_facing_commands(monkeypatch):
    from octryx_claude import cli

    seen = []
    monkeypatch.setattr(entry, "native_windows", lambda: False)
    monkeypatch.setattr(self_update, "on_start", lambda argv, err: seen.append(list(argv)))
    monkeypatch.setattr(cli, "main", lambda argv: 0)
    entry.main(["hook", "stop"])
    entry.main(["device", "run"])
    assert seen == [["device", "run"]]


def test_device_updates_only_while_idle_then_stops(installed):  # noqa: F811
    manager, checks, updated = FakeManager(), [], _updated(installed)

    def check():
        checks.append(bool(manager.turns))
        return updated if len(checks) > 1 else None

    async def scenario():
        stop = asyncio.Event()
        manager.turns = {"job": object()}
        task = asyncio.create_task(device_runtime.update_watch(manager, stop, check=check, interval=0.01,
                                                               idle_poll=0.01))
        await asyncio.sleep(0.05)
        assert checks == []  # a running job: no check, no update
        manager.turns = {}
        result = await asyncio.wait_for(task, 2)
        return result, stop.is_set()

    result, stopped = asyncio.run(scenario())
    assert result is updated and stopped and manager.draining
    assert checks == [False, False]


def test_device_waits_for_a_job_that_started_during_the_build(installed):  # noqa: F811
    manager, updated = FakeManager(), _updated(installed)

    def check():
        manager.turns = {"job": object()}  # an offer arrived while the new venv was built
        return updated

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(device_runtime.update_watch(manager, stop, check=check, interval=0.01,
                                                               idle_poll=0.01))
        await asyncio.sleep(0.1)
        assert not stop.is_set() and not task.done()
        manager.turns = {}
        return await asyncio.wait_for(task, 2), stop.is_set()

    assert asyncio.run(scenario()) == (updated, True)


def test_draining_device_rejects_new_turns(state):
    manager = JobManager(state)
    manager.draining = True
    assert manager._rejection({"job_id": "j"}, {}) == ("device_updating", "")


def test_device_run_re_executes_after_an_update(state, installed, monkeypatch):  # noqa: F811
    from octryx_claude import device_state

    monkeypatch.setattr(device_state, "load_device", lambda _state: {"device_id": "dev_1"})

    async def serve(_state, _stop):
        return _updated(installed)

    calls = []
    monkeypatch.setattr(device_runtime, "serve", serve)
    monkeypatch.setattr(self_update, "restart", lambda argv, updated, err: calls.append(argv))
    assert device_runtime.run_service(state) == device_runtime.EXIT_RESTART_FOR_UPDATE
    assert calls == [("device", "run")]


def test_service_units_restart_a_non_zero_exit():
    import plistlib

    from octryx_claude import device_service

    plist = plistlib.loads(device_service.launchd_plist(Path("/s"), Path("/l")))
    assert plist["KeepAlive"] == {"SuccessfulExit": False}  # restarts on EXIT_RESTART_FOR_UPDATE
    assert "Restart=on-failure" in device_service.systemd_unit(Path("/s"))
