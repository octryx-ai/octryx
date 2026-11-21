"""The device service's unit contents per OS (pure), its launchd label and the launchd reload (``device_service``)."""

from __future__ import annotations

import hashlib
import os
import plistlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

LAUNCHD_LABEL = "ai.octryx.claude.device"
SYSTEMD_UNIT = "octryx-claude-device.service"
WSL_TASK_NAME = "octryx-claude device"


def instance_label(base: str, *, home: Path | None = None, state_root: Path | None = None,
                   account_home: Path | None = None) -> str:
    """The launchd label of this installation: ``base`` for the standard one (the account's own HOME and the default
    state dir), ``base.<10 hex of the state dir>`` for every other one (a temporary HOME, ``OCTRYX_CLAUDE_HOME``).

    launchd labels live in the per-user domain ``gui/<uid>``, not in HOME: a second install with the same label
    would boot out the person's real pet with its ``bootstrap``. The standard install keeps the plain label, so its
    login items stay valid. ``installer/install.sh`` (``agent_label``) derives the same label.
    """
    import pwd  # noqa: PLC0415 - POSIX only; the native Windows pet imports this module too

    from .state import default_root  # noqa: PLC0415 - the state dir, as every command resolves it

    account = account_home or Path(pwd.getpwuid(os.getuid()).pw_dir)
    current_home = home or Path.home()
    root = state_root or default_root()
    if current_home == account and root == account / ".octryx" / "claude":
        return base
    return f"{base}.{hashlib.sha256(str(root).encode()).hexdigest()[:10]}"


def _systemd_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# --- unit contents (pure) -------------------------------------------------------------------------------------


def service_path() -> str:
    """The PATH the service runs with: the enabling user's PATH, so the service finds the same ``claude``,
    ``git`` and test tools as their shell (launchd itself starts with /usr/bin:/bin:/usr/sbin:/sbin)."""
    return os.environ.get("PATH", "") or "/usr/bin:/bin:/usr/sbin:/sbin"


def launchd_plist(shim: Path, log_file: Path, *, path: str | None = None, label: str = LAUNCHD_LABEL) -> bytes:
    """``ProcessType`` is ``Standard``: ``Background`` throttles CPU and I/O, which Claude Code turns do not survive
    well (the SDK's initialize handshake has 60 s)."""
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [str(shim), "device", "run"],
        "EnvironmentVariables": {"PATH": path or service_path()},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Standard",
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    })


def systemd_unit(shim: Path) -> str:
    exec_start = f"{_systemd_quote(str(shim))} device run"
    return (
        "[Unit]\n"
        "Description=octryx-claude device service (Octryx remote device sessions)\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def wsl_task_script(distro: str, shim: Path) -> str:
    """PowerShell that registers the logon task for the current Windows user only (no admin needed)."""
    arguments = f"-d {distro} -e {shim} device run"
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        f"$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument {_ps_quote(arguments)}; "
        "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); "
        f"Register-ScheduledTask -TaskName {_ps_quote(WSL_TASK_NAME)} -Trigger $trigger -Action $action "
        "-Settings $settings -Force | Out-Null; "
        f"Start-ScheduledTask -TaskName {_ps_quote(WSL_TASK_NAME)}"
    )


# ``launchctl bootout`` returns before launchd has unloaded the service; a ``bootstrap`` right after it fails with
# "Bootstrap failed: 5: Input/output error" (``launchd_command_failed`` on every re-enable).
BOOTOUT_WAIT_SECONDS = 5.0
BOOTOUT_POLL_SECONDS = 0.25


def launchd_reload(run: Callable[..., subprocess.CompletedProcess], *, uid: int, label: str, plist: Path,
                   sleep: Callable[[float], None] = time.sleep) -> None:
    """``bootout`` the service, wait until launchd no longer lists it, then ``bootstrap`` it (one retry).
    ``run(argv, required=...)`` raises on a required failure."""
    run(["launchctl", "bootout", f"gui/{uid}/{label}"], required=False)
    waited = 0.0
    while waited < BOOTOUT_WAIT_SECONDS:
        listed = run(["launchctl", "print", f"gui/{uid}/{label}"], required=False)
        if listed.returncode != 0 or not (listed.stdout or "").strip():  # 113: not loaded any more
            break
        sleep(BOOTOUT_POLL_SECONDS)
        waited += BOOTOUT_POLL_SECONDS
    if run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], required=False).returncode == 0:
        return
    sleep(1.0)
    run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], required=True)
