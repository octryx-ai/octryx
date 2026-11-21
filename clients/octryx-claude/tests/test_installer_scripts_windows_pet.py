"""install.ps1 for the Octryx pet on native Windows: Python lookup, the pet shim and the pet choice."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.installer_scripts_support import INSTALLER, PWSH, _pwsh, needs_pwsh, ps_env  # noqa: F401

# --- the Octryx pet on native Windows (install.ps1) ------------------------------------------------------------
# Only the parts that run without Windows: finding a Windows Python, the shim and account.json, and that a machine
# without such a Python still installs (with a hint) and -NoPet leaves the pet out. The venv build itself needs Windows.


def _ps_functions(script: Path, env: dict, command: str) -> subprocess.CompletedProcess:
    return subprocess.run([PWSH, "-NoProfile", "-Command", f". '{script}'; {command}"],
                          env={**env, "OCTRYX_INSTALLER_NO_RUN": "1"}, capture_output=True, text=True, check=False)


@needs_pwsh
def test_ps1_pet_finds_a_windows_python_and_skips_the_store_stub(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    store = tmp_path / "WindowsApps"
    store.mkdir()
    for folder, name, answer in ((store, "python.exe", "True"), (tmp_path / "fakebin", "py.exe", "False")):
        exe = folder / name
        exe.write_text(f"#!/bin/sh\necho {answer}\n")
        exe.chmod(0o755)
    env = {**env, "PATH": f"{store}:{env['PATH']}"}
    done = _ps_functions(script, env, "$p = Find-OctryxPetPython; if ($p) { $p -join '|' } else { 'NONE' }")
    assert done.stdout.strip() == "NONE", done.stdout + done.stderr  # py says < 3.11, the store stub is skipped
    (tmp_path / "fakebin" / "py.exe").write_text("#!/bin/sh\necho True\n")
    done = _ps_functions(script, env, "(Find-OctryxPetPython) -join '|'")
    assert done.stdout.strip() == f"{tmp_path / 'fakebin' / 'py.exe'}|-3", done.stdout + done.stderr


@needs_pwsh
def test_ps1_pet_shim_and_account_carry_no_secret_and_refuse_unsafe_values(ps_env):  # noqa: F811
    _, script, env = ps_env
    done = _ps_functions(script, env, (
        "Get-OctryxPetShimContent -Python 'C:\\Users\\Alice C\\venv\\Scripts\\python.exe'; '---'; "
        "Get-OctryxPetAccountJson -BaseUrl 'https://octryx.example.test' -Distribution 'Ubuntu' "
        "-WslHome '/home/t'; '---'; "
        "try { Get-OctryxPetAccountJson -BaseUrl 'x' -Distribution 'Ub&calc' -WslHome '/home/t' } catch { 'REFUSED' }; "
        "try { Get-OctryxPetShimContent -Python 'C:\\a&b\\python.exe' } catch { 'REFUSED' }"))
    shim, account, refused = done.stdout.split("---")
    assert '"C:\\Users\\Alice C\\venv\\Scripts\\python.exe" -m octryx_claude.pet %*' in shim
    assert "octryx-pet shim (managed by the Octryx installer)" in shim
    assert json.loads(account) == {"base_url": "https://octryx.example.test", "wsl_distribution": "Ubuntu",
                                   "wsl_home": "/home/t"}
    assert refused.split() == ["REFUSED", "REFUSED"], done.stdout + done.stderr


@needs_pwsh
def test_ps1_install_without_a_windows_python_names_it_and_succeeds(ps_env):  # noqa: F811
    tmp_path, script, env = ps_env
    done = _pwsh(script, env, "install", "-NoLogin")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "needs Python 3.11 or newer on Windows: winget install Python.Python.3.12" in done.stdout
    assert not (tmp_path / "localappdata" / "Octryx" / "octryx-claude" / "pet").exists()
    quiet = _pwsh(script, env, "install", "-NoLogin", "-NoPet")
    assert quiet.returncode == 0 and "Octryx pet" not in quiet.stdout, quiet.stdout + quiet.stderr


def test_ps1_turns_the_pet_on_unless_turned_off_and_uninstall_keeps_that_choice_out():
    # On by default: `pet autostart` writes the Run key and starts it, but respects a
    # `pet disable` / "Turn off Octryx"; uninstall drops the Run key without recording "turned off".
    text = (INSTALLER / "install.ps1").read_text(encoding="utf-8")
    install = text.split("function Install-OctryxPet", 1)[1].split("function Uninstall-OctryxPet", 1)[0]
    uninstall = text.split("function Uninstall-OctryxPet", 1)[1].split("\n}", 1)[0]
    assert "& $venvPython -m octryx_claude.pet autostart" in install
    assert "Remove-OctryxPetAutostart" in uninstall and "pet disable" not in uninstall.replace("`pet disable`", "")
