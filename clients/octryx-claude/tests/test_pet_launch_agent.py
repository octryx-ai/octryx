"""The pet's LaunchAgent, login item, menu turn-off and the pet subcommands."""

from __future__ import annotations

import plistlib
import subprocess
import sys

import pytest

from octryx_claude import cli
from octryx_claude.pet import cli as pet_cli
from octryx_claude.pet import settings as pet_settings
from octryx_claude.pet.service import LAUNCHD_LABEL, LaunchAgent, PetServiceError


@pytest.fixture
def mac_agent(state, tmp_path, monkeypatch):
    calls = []

    def runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    agent = LaunchAgent(home=tmp_path / "home", uid=501, runner=runner)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pet_cli, "_launch_agent", lambda: agent)
    monkeypatch.setattr(pet_cli, "_pet_extra_present", lambda: True)
    monkeypatch.setattr(pet_cli, "in_wsl", lambda: False)
    return agent, calls


# --- LaunchAgent and CLI ---------------------------------------------------------------------------------------


def test_the_launch_agent_is_installed_and_removed_as_the_user(tmp_path):
    calls = []

    def runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    agent = LaunchAgent(home=tmp_path, uid=501, runner=runner)
    agent.install(["/home/u/.local/bin/octryx-claude"], tmp_path / "pet.log")
    plist = plistlib.loads(agent.path.read_bytes())
    assert plist["Label"] == LAUNCHD_LABEL and plist["ProgramArguments"][-2:] == ["pet", "run"]
    assert plist["KeepAlive"] == {"SuccessfulExit": False} and plist["LimitLoadToSessionType"] == "Aqua"
    assert calls == [["launchctl", "bootout", f"gui/501/{LAUNCHD_LABEL}"],
                     ["launchctl", "print", f"gui/501/{LAUNCHD_LABEL}"],
                     ["launchctl", "bootstrap", "gui/501", str(agent.path)]]
    agent.remove()
    assert not agent.installed()
    failing = LaunchAgent(home=tmp_path, uid=501, runner=lambda argv: subprocess.CompletedProcess(argv, 5, "", ""))
    with pytest.raises(PetServiceError):
        failing.install(["x"], tmp_path / "pet.log")


def test_an_unchanged_running_agent_is_left_alone_and_removal_drops_the_file_first(tmp_path):
    calls = []

    def runner(argv):
        calls.append((list(argv), agent.path.exists()))
        return subprocess.CompletedProcess(argv, 0, "", "")

    agent = LaunchAgent(home=tmp_path, uid=501, runner=runner)
    assert agent.install(["/s/octryx-claude"], tmp_path / "pet.log", restart=False)  # not there yet: started
    calls.clear()
    assert not agent.install(["/s/octryx-claude"], tmp_path / "pet.log", restart=False)
    assert calls == [(["launchctl", "print", f"gui/501/{LAUNCHD_LABEL}"], True)]  # only asked whether it runs
    assert agent.install(["/s/octryx-claude"], tmp_path / "pet.log", restart=True)  # a new version: restarted
    calls.clear()
    agent.remove()
    # The pet turning itself off is ended by the bootout: by then the login item must already be gone.
    assert calls == [(["launchctl", "bootout", f"gui/501/{LAUNCHD_LABEL}"], False)]


def test_the_pet_is_on_by_default_and_stays_off_once_turned_off(state, mac_agent, capsys):
    agent, calls = mac_agent
    assert cli.main(["pet", "autostart"]) == 0  # what the installer runs: on by default
    assert agent.installed() and "starts at every login" in capsys.readouterr().out
    assert cli.main(["pet", "disable"]) == 0
    assert not agent.installed() and pet_settings.autostart_off(state.root)
    calls.clear()
    assert cli.main(["pet", "autostart", "--restart"]) == 0  # an update respects the choice
    assert not agent.installed() and calls == [] and "stays off" in capsys.readouterr().out
    assert cli.main(["pet", "enable"]) == 0
    assert agent.installed() and not pet_settings.autostart_off(state.root)


def test_without_the_pet_extra_the_login_item_goes(state, mac_agent, monkeypatch, capsys):
    agent, _calls = mac_agent
    assert cli.main(["pet", "enable"]) == 0 and agent.installed()
    monkeypatch.setattr(pet_cli, "_pet_extra_present", lambda: False)
    assert cli.main(["pet", "autostart"]) == 2  # never a login item that fails at every login
    assert not agent.installed() and not pet_settings.autostart_off(state.root)
    assert "pip install 'octryx-claude[pet]'" in capsys.readouterr().err


def test_turn_off_from_the_menu_is_pet_disable(state, mac_agent, monkeypatch):
    agent, _calls = mac_agent
    assert cli.main(["pet", "enable"]) == 0

    class FakeTray:
        def __init__(self, factory):
            self.turned_off = False

        def run(self):
            self.turned_off = True  # the person chose "Turn off Octryx (also at login)"

    import octryx_claude.pet.tray as tray_module  # noqa: PLC0415

    monkeypatch.setattr(tray_module, "Tray", FakeTray)
    assert cli.main(["pet", "run"]) == 0
    assert not agent.installed() and pet_settings.autostart_off(state.root)


def test_pet_quiet_and_notifications_subcommands(state, capsys):
    assert cli.main(["pet", "quiet", "19:00-08:00"]) == 0
    assert "19:00–08:00 (on, local time)" in capsys.readouterr().out
    assert cli.main(["pet", "quiet", "off"]) == 0
    assert not pet_settings.load(state.root).quiet_hours.enabled
    assert cli.main(["pet", "quiet", "late"]) == 2
    assert cli.main(["pet", "notifications", "off"]) == 0
    assert pet_settings.load(state.root).notifications is False
    assert pet_settings.load(state.root).quiet_hours.label() == "19:00–08:00"


def test_bootstrap_waits_for_the_bootout_and_retries_once(tmp_path):
    """launchctl bootout returns before the service is unloaded; bootstrap right after fails with EIO."""
    calls, prints, bootstraps, sleeps = [], iter([0, 0, 113]), iter([5, 0]), []

    def runner(argv):
        calls.append(argv[1])
        if argv[1] == "print":
            code = next(prints)
            return subprocess.CompletedProcess(argv, code, "state = running" if code == 0 else "", "")
        if argv[1] == "bootstrap":
            return subprocess.CompletedProcess(argv, next(bootstraps), "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    agent = LaunchAgent(home=tmp_path, uid=501, runner=runner)
    agent.sleep = sleeps.append
    agent.install(["/home/u/.local/bin/octryx-claude"], tmp_path / "pet.log")
    assert calls == ["bootout", "print", "print", "print", "bootstrap", "bootstrap"]
    assert sleeps[-1] == 1.0 and len(sleeps) == 3
