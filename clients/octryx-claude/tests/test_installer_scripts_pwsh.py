"""install.ps1 run with PowerShell against a fake wsl.exe: install, login, refusals and uninstall."""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.installer_scripts_support import BASE_URL, PWSH, _pwsh, needs_pwsh, ps_env  # noqa: F401


@needs_pwsh
def test_ps1_parses_without_errors(ps_env):  # noqa: F811
    _, script, env = ps_env
    command = ("$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
               f"'{script}', [ref]$null, [ref]$errors) | Out-Null; $errors.Count")
    done = subprocess.run([PWSH, "-NoProfile", "-Command", command], env=env, capture_output=True, text=True,
                          check=False)
    assert done.stdout.strip() == "0", done.stdout + done.stderr


@needs_pwsh
def test_ps1_path_value_is_idempotent_and_removable(ps_env):  # noqa: F811
    _, script, env = ps_env
    command = (f". '{script}'; "
               "$a = Get-OctryxPathValue -Current 'C:\\a;;C:\\b\\' -Entry 'C:\\b'; "
               "$b = Get-OctryxPathValue -Current $a -Entry 'C:\\b'; "
               "$c = Get-OctryxPathValue -Current $b -Entry 'C:\\b' -Remove; "
               "@($a, $b, $c) | ConvertTo-Json -Compress")
    done = subprocess.run([PWSH, "-NoProfile", "-Command", command], env={**env, "OCTRYX_INSTALLER_NO_RUN": "1"},
                          capture_output=True, text=True, check=False)
    assert json.loads(done.stdout) == ["C:\\a;C:\\b", "C:\\a;C:\\b", "C:\\a"], done.stderr


@needs_pwsh
def test_ps1_shim_content_refuses_unsafe_values(ps_env):  # noqa: F811
    _, script, env = ps_env
    command = (f". '{script}'; "
               "Get-OctryxShimContent -Distribution 'Ubuntu' -WslHome '/home/tester'; "
               "try { Get-OctryxShimContent -Distribution 'Ub&calc' -WslHome '/home/tester' } "
               "catch { 'REFUSED' }")
    done = subprocess.run([PWSH, "-NoProfile", "-Command", command], env={**env, "OCTRYX_INSTALLER_NO_RUN": "1"},
                          capture_output=True, text=True, check=False)
    assert "wsl.exe -d Ubuntu -e /home/tester/.local/bin/octryx-claude %*" in done.stdout
    assert done.stdout.strip().endswith("REFUSED"), done.stdout + done.stderr


@needs_pwsh
def test_ps1_install_runs_install_sh_in_wsl_and_writes_shim(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    done = _pwsh(script, env, "install", "-NoLogin")
    assert done.returncode == 0, done.stdout + done.stderr
    log = (tmp_path / "wsl.log").read_text().splitlines()
    assert (f"-d Ubuntu -e bash -c set -o pipefail; curl -fsSL '{BASE_URL}/octryx-claude/install.sh' "
            "| bash -s -- install --no-login") in log, log
    assert "install.sh install --no-login" in log  # the downloaded script ran
    assert "-d Ubuntu -e test -x /home/tester/.local/bin/octryx-claude" in log
    assert not any(" login " in f" {line} " for line in log)  # -NoLogin
    assert "-d Ubuntu -e /home/tester/.local/bin/octryx-claude status" in log
    shim = tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "bin" / "octryx-claude.cmd"
    content = shim.read_bytes()
    assert b"managed by the Octryx installer" in content
    assert b"\r\n" in content
    alias = (shim.parent / "octryx.cmd").read_bytes()  # the short name calls the shim next to it
    assert b'call "%~dp0octryx-claude.cmd" %*' in alias and b"octryx command (managed by" in alias
    assert not (tmp_path / "home" / ".claude").exists()


@needs_pwsh
def test_ps1_install_logs_in_with_workspace(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    done = _pwsh(script, env, "install", "-Workspace", "ws-1")
    assert done.returncode == 0, done.stdout + done.stderr
    log = (tmp_path / "wsl.log").read_text().splitlines()
    assert (f"-d Ubuntu -e /home/tester/.local/bin/octryx-claude login --base-url {BASE_URL} --workspace ws-1"
            in log), log


@needs_pwsh
@pytest.mark.parametrize(
    ("extra", "args", "message"),
    [
        ({"FAKE_WSL_KERNEL": "4.4.0-19041-Microsoft"}, ["install"], "runs on WSL1"),
        ({"FAKE_WSL_NO_DISTRO": "1"}, ["install"], "no usable WSL distribution"),
        ({"FAKE_WSL_BASH_RC": "3"}, ["install", "-NoLogin"], "the install inside WSL failed"),
        ({"FAKE_CURL_RC": "22"}, ["install", "-NoLogin"], "the install inside WSL failed"),
        ({"FAKE_WSL_NO_SHIM": "1"}, ["install", "-NoLogin"], "left no /home/tester/.local/bin/octryx-claude"),
        ({}, ["install", "-Workspace", "\"x';calc\""], "unusable Workspace"),
    ],
)
def test_ps1_refuses_explicitly(ps_env, extra, args, message):  # noqa: F811
    tmp_path, script, env = ps_env
    done = _pwsh(script, env, *args, extra=extra)
    assert done.returncode != 0
    assert message in done.stdout + done.stderr
    assert not (tmp_path / "localappdata" / "Octryx").exists()


@needs_pwsh
def test_ps1_without_wsl_names_the_one_time_setup(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    (tmp_path / "fakebin" / "wsl.exe").unlink()
    done = _pwsh(script, env, "install")
    assert done.returncode != 0
    assert "wsl --install" in done.stdout + done.stderr


@needs_pwsh
def test_ps1_uninstall_purge_runs_in_wsl_and_removes_own_shim(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    assert _pwsh(script, env, "install", "-NoLogin").returncode == 0
    done = _pwsh(script, env, "uninstall", "-Purge")
    assert done.returncode == 0, done.stdout + done.stderr
    log = (tmp_path / "wsl.log").read_text()
    assert "install.sh uninstall --purge" in log
    assert not (tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "bin" / "octryx-claude.cmd").exists()
    assert not (tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "bin" / "octryx.cmd").exists()
    assert not (tmp_path / "localappdata" / "Octryx").exists()  # created by the installer, empty again
    assert (tmp_path / "localappdata").is_dir()  # LOCALAPPDATA itself is never removed


@needs_pwsh
def test_ps1_no_login_hands_the_workspace_to_install_sh(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    done = _pwsh(script, env, "install", "-NoLogin", "-Workspace", "ws-1")
    assert done.returncode == 0, done.stdout + done.stderr
    log = (tmp_path / "wsl.log").read_text().splitlines()
    assert "install.sh install --no-login --workspace ws-1" in log, log
    assert not any(" login " in f" {line} " for line in log)


@needs_pwsh
def test_ps1_uninstall_keeps_pre_existing_and_non_empty_directories(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    vendor = tmp_path / "localappdata" / "Octryx"
    vendor.mkdir(parents=True)  # pre-existing and empty: never recorded, never removed
    assert _pwsh(script, env, "install", "-NoLogin").returncode == 0
    bin_dir = vendor / "octryx-claude" / "bin"
    (bin_dir / "mine.cmd").write_bytes(b"@echo mine\r\n")
    assert _pwsh(script, env, "uninstall").returncode == 0
    assert (bin_dir / "mine.cmd").read_bytes() == b"@echo mine\r\n"  # non-empty: kept, still recorded
    assert not (bin_dir / "octryx-claude.cmd").exists()
    (bin_dir / "mine.cmd").unlink()
    assert _pwsh(script, env, "uninstall").returncode == 0
    assert not (vendor / "octryx-claude").exists()
    assert vendor.is_dir() and not any(vendor.iterdir())


@needs_pwsh
def test_ps1_uninstall_with_a_failed_download_fails_and_keeps_the_shim(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    assert _pwsh(script, env, "install", "-NoLogin").returncode == 0
    done = _pwsh(script, env, "uninstall", extra={"FAKE_CURL_RC": "22"})
    assert done.returncode != 0
    assert "uninstall inside WSL failed" in done.stdout + done.stderr
    assert (tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "bin" / "octryx-claude.cmd").exists()


@needs_pwsh
def test_ps1_never_overwrites_a_foreign_shim(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    bin_dir = tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "octryx-claude.cmd").write_bytes(b"@echo mine\r\n")
    done = _pwsh(script, env, "install", "-NoLogin")
    assert done.returncode != 0
    assert (bin_dir / "octryx-claude.cmd").read_bytes() == b"@echo mine\r\n"
