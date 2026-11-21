"""The OS service units (launchd, systemd, WSL logon task) the device CLI installs and their failures."""

from __future__ import annotations

import plistlib
import subprocess

import pytest

from octryx_claude import device_runtime, device_service, device_service_units, device_state
from tests.device_cli_support import no_service_probe  # noqa: F401


class Runner:
    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, self.stdout, "")


def test_launchd_agent_is_per_user_and_keeps_alive_on_failure(tmp_path):
    runner = Runner()
    manager = device_service.LaunchdManager(home=tmp_path, runner=runner, uid=501)
    shim = tmp_path / ".local" / "bin" / "octryx-claude"
    manager.install(shim, tmp_path / "device.log")
    plist = plistlib.loads(manager.unit_path.read_bytes())
    assert manager.unit_path.parent == tmp_path / "Library" / "LaunchAgents"
    assert plist["ProgramArguments"] == [str(shim), "device", "run"]
    assert plist["KeepAlive"] == {"SuccessfulExit": False} and plist["RunAtLoad"] is True
    assert plist["ProcessType"] == "Standard" and plist["EnvironmentVariables"]["PATH"]
    assert runner.calls[-1] == ["launchctl", "bootstrap", "gui/501", str(manager.unit_path)]
    manager.uninstall()
    assert not manager.unit_path.exists()
    assert runner.calls[-1] == ["launchctl", "bootout", "gui/501/ai.octryx.claude.device"]


def test_a_plist_that_is_not_the_current_definition_is_replaced_keeping_the_path(tmp_path, state,
                                                                                          monkeypatch):
    runner, spawned = Runner(), []
    manager = device_service.LaunchdManager(home=tmp_path, runner=runner, uid=501, spawn=spawned.append)
    shim, log = tmp_path / "shim", tmp_path / "device.log"
    differing = plistlib.loads(device_service.launchd_plist(shim, log, path="/opt/homebrew/bin:/usr/bin"))
    differing["ProcessType"] = "Background"
    manager.unit_path.parent.mkdir(parents=True)
    manager.unit_path.write_bytes(plistlib.dumps(differing))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # launchd's own PATH inside the service
    assert manager.reconcile(shim, log) is True
    plist = plistlib.loads(manager.unit_path.read_bytes())
    assert plist["ProcessType"] == "Standard" and plist["EnvironmentVariables"]["PATH"] == "/opt/homebrew/bin:/usr/bin"
    assert manager.reconcile(shim, log) is False  # already the current definition: no reload loop
    assert runner.calls == [] and spawned == []

    manager.unit_path.write_bytes(plistlib.dumps(differing))
    device_state.save_device(state, {"device_id": "dev_x", "os": "macos", "service_kind": "launchd"})
    monkeypatch.setattr(device_service, "service_shim", lambda: shim)
    monkeypatch.setattr(device_state, "log_path", lambda state: log)
    assert device_runtime.reconcile_service_unit(state, manager=manager, env={}) == "replaced"  # not inside launchd
    manager.unit_path.write_bytes(plistlib.dumps(differing))
    launchd_env = {"XPC_SERVICE_NAME": device_service.LAUNCHD_LABEL}
    assert device_runtime.reconcile_service_unit(state, manager=manager, env=launchd_env) == "reloading"
    script = spawned[0][-1]
    assert spawned[0][:2] == ["/bin/sh", "-c"] and "launchctl bootout gui/501/" in script
    assert script.index("bootout") < script.index("bootstrap gui/501")
    assert device_runtime.reconcile_service_unit(state, manager=manager, env=launchd_env) == ""


def test_a_systemd_unit_that_is_not_the_current_definition_is_replaced_and_reloaded(tmp_path):
    runner = Runner()
    manager = device_service.SystemdManager(home=tmp_path, runner=runner)
    shim = tmp_path / "octryx-claude"
    assert manager.reconcile(shim, tmp_path / "device.log") is False  # nothing installed: enable installs it
    manager.unit_path.parent.mkdir(parents=True)
    manager.unit_path.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    assert manager.reconcile(shim, tmp_path / "device.log") is True
    assert manager.unit_path.read_text(encoding="utf-8") == device_service_units.systemd_unit(shim)
    assert runner.calls == [["systemctl", "--user", "daemon-reload"]]
    assert manager.reconcile(shim, tmp_path / "device.log") is False


def test_systemd_user_unit_never_uses_root_or_linger(tmp_path):
    runner = Runner(stdout="active\n")
    manager = device_service.SystemdManager(home=tmp_path, runner=runner)
    manager.install(tmp_path / "shim dir" / "octryx-claude", tmp_path / "device.log")
    unit = manager.unit_path.read_text()
    assert f'ExecStart="{tmp_path / "shim dir" / "octryx-claude"}" device run' in unit and "Restart=on-failure" in unit
    assert all(call[:2] == ["systemctl", "--user"] for call in runner.calls)
    assert not any("linger" in " ".join(call) or "sudo" in call for call in runner.calls)
    assert manager.status().running is True


def test_wsl_logon_task_runs_the_shim_in_the_distro_for_the_current_user_only(tmp_path):
    runner = Runner(stdout="Running\n")
    manager = device_service.WslTaskManager(home=tmp_path, runner=runner, distro="Ubuntu")
    manager.install(tmp_path / "octryx-claude", tmp_path / "device.log")
    script = runner.calls[0][-1]
    assert runner.calls[0][0] == "powershell.exe"
    assert "-AtLogOn -User $env:USERNAME" in script and "wsl.exe" in script
    assert f"-d Ubuntu -e {tmp_path / 'octryx-claude'} device run" in script
    assert manager.status().running is True
    with pytest.raises(device_service.ServiceError):
        device_service.WslTaskManager(home=tmp_path, runner=runner, distro="")


def test_a_failing_service_command_is_a_fixed_code(tmp_path):
    def failing(argv):
        return subprocess.CompletedProcess(argv, 1, "", "boom")

    manager = device_service.SystemdManager(home=tmp_path, runner=failing)
    with pytest.raises(device_service.ServiceError) as raised:
        manager.install(tmp_path / "octryx-claude", tmp_path / "device.log")
    assert raised.value.code == "systemd_command_failed"


def test_a_second_installation_gets_its_own_launchd_labels_and_never_boots_out_the_first(tmp_path, monkeypatch):
    """Labels live in gui/<uid>, not in HOME, so they differ per installation: a second install's bootstrap never boots
    out the person's real pet."""
    from octryx_claude.pet import cli as pet_cli
    from octryx_claude.pet.service import LAUNCHD_LABEL as PET_LABEL

    account = tmp_path / "account"
    standard = account / ".octryx" / "claude"
    base = device_service.LAUNCHD_LABEL
    label = device_service.instance_label
    assert label(base, home=account, state_root=standard, account_home=account) == base  # the account's own install
    other_home = label(base, home=tmp_path / "tmp-home", state_root=tmp_path / "tmp-home" / ".octryx" /
                       "octryx-claude", account_home=account)
    other_state = label(base, home=account, state_root=account / "second", account_home=account)
    assert other_home.startswith(base + ".") and other_state.startswith(base + ".") and other_home != other_state
    assert label(base, home=account, state_root=account / "second", account_home=account) == other_state  # stable

    temp_home = tmp_path / "temp-home"
    monkeypatch.setenv("HOME", str(temp_home))
    monkeypatch.delenv("OCTRYX_CLAUDE_HOME", raising=False)
    calls = []

    def runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    manager = device_service.manager_for("macos", runner=runner, uid=501)
    manager.install(temp_home / ".local" / "bin" / "octryx-claude", temp_home / "device.log")
    pet = pet_cli._launch_agent()
    assert manager.label != base and pet.label != PET_LABEL
    assert plistlib.loads(manager.unit_path.read_bytes())["Label"] == manager.label
    assert manager.unit_path.name == f"{manager.label}.plist"
    assert all(f"gui/501/{base}" not in " ".join(call) or manager.label in " ".join(call) for call in calls)
    assert device_service.launched_by_launchd({"XPC_SERVICE_NAME": manager.label})
    assert not device_service.launched_by_launchd({"XPC_SERVICE_NAME": "com.other.agent"})
