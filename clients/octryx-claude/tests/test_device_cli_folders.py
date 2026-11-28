from __future__ import annotations

import argparse

import pytest

from octryx_claude import device_cli, device_folder_access, device_state
from octryx_claude.state import LocalState
from tests.device_cli_support import FakeManager, no_service_probe  # noqa: F401


def _registered(state: LocalState, folders: list[str]) -> None:
    device_state.save_device(state, {"device_id": "dev_x", "name": "Box", "os": "linux", "folders": folders,
                                     "max_parallel_jobs": 4, "paused": False})


def test_folders_widen_only_with_a_local_confirmation(state, tmp_path, capsys):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    _registered(state, [str(first.resolve())])
    add = argparse.Namespace(folder_action="add", path=str(second), yes=False)
    assert device_cli.run_folders(add, state, ask=lambda prompt: "n\n") == 2
    assert device_state.load_device(state)["folders"] == [str(first.resolve())]
    assert device_cli.run_folders(add, state, ask=lambda prompt: "y\n") == 0
    assert device_state.load_device(state)["folders"] == [str(first.resolve()), str(second.resolve())]
    remove = argparse.Namespace(folder_action="remove", path=str(first), yes=False)
    assert device_cli.run_folders(remove, state) == 0
    assert device_state.load_device(state)["folders"] == [str(second.resolve())]


def test_a_folder_the_service_cannot_read_is_refused_with_the_next_step(state, tmp_path, capsys, monkeypatch):
    first, blocked = tmp_path / "one", tmp_path / "blocked"
    first.mkdir()
    blocked.mkdir()
    device_state.save_device(state, {"device_id": "dev_x", "name": "Box", "os": "macos", "folders": [str(first)],
                                     "max_parallel_jobs": 4, "paused": False})
    add = argparse.Namespace(folder_action="add", path=str(blocked), yes=True)
    # This process cannot read it either: refused before anything is asked.
    monkeypatch.setattr(device_folder_access, "access_problem",
                        lambda folder: device_folder_access.REASON_NOT_ACCESSIBLE if folder.endswith("blocked") else "")
    assert device_cli.run_folders(add, state) == 2
    err = capsys.readouterr().err
    assert "device_folder_not_accessible" in err and "Full Disk Access" in err and "folder in your home" in err
    # The terminal may read it while the running service may not: the service's answer decides.
    monkeypatch.setattr(device_folder_access, "access_problem", lambda folder: "")
    device_state.write_status(state, {"folder_access_at": 10**12, "service_python": "/opt/py/bin/python3.12"})
    monkeypatch.setattr(device_folder_access, "service_alive", lambda state: True)
    answers = {str(blocked.resolve()): device_folder_access.REASON_NOT_ACCESSIBLE}
    assert device_cli.run_folders(add, state, probe=lambda state, folders: answers) == 2
    assert "/opt/py/bin/python3.12" in capsys.readouterr().err
    assert device_state.load_device(state)["folders"] == [str(first)]
    assert device_cli.run_folders(add, state, probe=lambda state, folders: {folders[0]: ""}) == 0
    # `device status` shows the service's verdict per folder.
    device_state.write_status(state, {"folder_access": {str(first): device_folder_access.REASON_NOT_ACCESSIBLE},
                                      "service_python": "/opt/py/bin/python3.12"})
    assert device_cli.run_status(state, manager=FakeManager()) == 0
    out = capsys.readouterr().out
    assert f"{first} · device_folder_not_accessible: macOS blocks the background service" in out


def test_the_access_probe_lists_the_folder_and_the_service_answers_requests(state, tmp_path, monkeypatch):
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "README").write_text("x")
    assert device_folder_access.access_problem(str(folder)) == ""

    def denied(path):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(device_folder_access.os, "scandir", denied)
    assert device_folder_access.access_problem(str(folder)) == "device_folder_not_accessible"
    request_id = device_folder_access.request_probe(state, [str(folder)])
    assert device_folder_access.answer_probe(state) is True
    probe = device_state.read_status(state)["folder_probe"]
    assert probe["id"] == request_id and probe["results"] == {str(folder): "device_folder_not_accessible"}
    assert not (state.root / device_folder_access.PROBE_FILE).exists()


def test_pause_parallel_and_status(state, capsys):
    _registered(state, [])
    assert device_cli.run_pause(state, True) == 0
    assert device_state.load_device(state)["paused"] is True
    assert device_cli.run_parallel(argparse.Namespace(count=8), state) == 0
    assert device_cli.run_parallel(argparse.Namespace(count=0), state) == 2
    assert device_state.load_device(state)["max_parallel_jobs"] == 8
    device_state.write_status(state, {"connected": True, "running_jobs": 2})
    assert device_cli.run_status(state, manager=FakeManager()) == 0
    out = capsys.readouterr().out
    assert "paused" in out and "connected · 2 running" in out and "systemd · running" in out


def test_folder_check_resolves_symlinks_out_of_the_allowlist(tmp_path):
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "sub").mkdir()
    (allowed / "escape").symlink_to(outside)
    roots = [str(allowed)]
    assert device_state.folder_allowed(str(allowed / "sub"), roots) == str((allowed / "sub").resolve())
    assert device_state.folder_allowed(str(allowed / "escape"), roots) == ""
    assert device_state.folder_allowed(str(outside), roots) == ""
    assert device_state.folder_allowed(str(tmp_path / "missing"), roots) == ""


def test_detect_os_and_macos_protected_folder_warning(tmp_path):
    assert device_state.detect_os(system="Darwin", release="25.0", env={}) == "macos"
    assert device_state.detect_os(system="Linux", release="6.6.87.2-microsoft-standard-WSL2", env={}) == "wsl2"
    assert device_state.detect_os(system="Linux", release="6.8.0", env={"WSL_DISTRO_NAME": "Ubuntu"}) == "wsl2"
    assert device_state.detect_os(system="Linux", release="6.8.0", env={}) == "linux"
    with pytest.raises(device_state.DeviceStateError):
        device_state.detect_os(system="Windows", release="11", env={})
    home = tmp_path
    assert "Documents" in device_state.protected_folder_warning(str(home / "Documents" / "repo"), os_name="macos",
                                                                home=home)
    assert device_state.protected_folder_warning(str(home / "src"), os_name="macos", home=home) == ""


def test_status_names_revoked_idle_reasons_errors_and_a_stale_connected(state, capsys):
    import time

    _registered(state, [])
    device = device_state.load_device(state)
    device["revoked"] = True
    device_state.save_device(state, device)
    device_cli.run_status(state, manager=FakeManager())
    assert "· revoked" in capsys.readouterr().out

    device.pop("revoked")
    device_state.save_device(state, device)
    device_state.write_status(state, {"connected": False, "idle_reason": "needs_login"})
    device_cli.run_status(state, manager=FakeManager())
    assert "offline (needs_login)" in capsys.readouterr().out

    device_state.write_status(state, {"connected": False, "last_error": "platform_unreachable", "attempt": 7})
    device_cli.run_status(state, manager=FakeManager())
    assert "offline (last error: platform_unreachable, attempt 7)" in capsys.readouterr().out

    device_state.write_status(state, {"connected": True, "running_jobs": 0, "updated_at": time.time() - 600})
    device_cli.run_status(state, manager=FakeManager())
    assert "unknown (status stale" in capsys.readouterr().out
