"""The device background service per OS: install, remove and inspect it, as the user, never as root.

- macOS: a per-user **LaunchAgent** ``~/Library/LaunchAgents/ai.octryx.claude.device.plist``
  (``RunAtLoad``, ``KeepAlive={SuccessfulExit: false}``, ``ThrottleInterval=30``, ``ProcessType=Standard``, the
  enabling user's ``PATH``), loaded with ``launchctl bootstrap gui/<uid>`` and removed with ``bootout``. It runs
  while the user is logged in. ``device enable`` installs the unit; every service start reconciles it
  (:meth:`reconcile`): an installed unit whose content is not this version's definition is replaced by it, keeping
  the ``PATH`` chosen at enable, and loaded again (``reload_detached``).
- Linux: a **systemd user unit** ``~/.config/systemd/user/octryx-claude-device.service``
  (``Restart=on-failure``, ``RestartSec=10``), ``systemctl --user enable --now``. Lingering for headless hosts
  is the user's own choice (``loginctl enable-linger``), never done here.
- Windows (WSL2): a **scheduled task** at the user's own logon, created through PowerShell without admin
  rights, that runs ``wsl.exe -d <distro> -e <shim> device run``; the running process keeps the WSL VM alive.

Every unit calls the ``current`` shim (``~/.local/bin/octryx-claude``). The service updates itself (
``device_runtime.update_watch``): at start and every five minutes while no job runs; it then re-executes ``device
run`` in place, which needs no restart policy (the WSL logon task has none for an exiting process). Only if that
re-exec fails it exits non-zero, which ``KeepAlive.SuccessfulExit=false`` and ``Restart=on-failure`` restart.
All OS commands go through an injectable ``runner``; the tests use a fake and a temporary HOME.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import install_layout
from .device_service_units import (
    LAUNCHD_LABEL,
    SYSTEMD_UNIT,
    WSL_TASK_NAME,
    _ps_quote,
    _sh_quote,
    instance_label,
    launchd_plist,
    launchd_reload,
    systemd_unit,
    wsl_task_script,
)
from .device_state import OS_LINUX, OS_MACOS, OS_WSL2

KIND_FOR_OS = {OS_MACOS: "launchd", OS_LINUX: "systemd", OS_WSL2: "wsl-task"}
COMMAND_TIMEOUT = 30.0

RELOAD_DELAY_SECONDS = 2

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
Spawn = Callable[[Sequence[str]], object]


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False)


def default_spawn(argv: Sequence[str]) -> object:
    return subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


class ServiceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def service_shim(home: Path | None = None) -> Path:
    """The ``current`` shim when installed, else this copy's own launcher."""
    shim = (home or Path.home()) / ".local" / "bin" / "octryx-claude"
    return shim if shim.exists() else install_layout.launcher_shim()


# --- managers -------------------------------------------------------------------------------------------------


@dataclass
class ServiceStatus:
    kind: str
    installed: bool
    running: bool


class _Manager:
    kind = ""

    def __init__(self, *, home: Path, runner: Runner) -> None:
        self.home = home
        self.runner = runner

    def reconcile(self, shim: Path, log_file: Path) -> bool:
        """Make an installed unit this version's definition; ``True`` when its file was replaced. Only the file
        changes: a running service keeps running, :meth:`install` or :meth:`reload_detached` loads it."""
        return False

    def reload_detached(self) -> bool:
        """Load the replaced unit from a helper outside the service's own process group; ``False`` if unsupported."""
        return False

    def _run(self, argv: Sequence[str], *, required: bool = True) -> subprocess.CompletedProcess:
        try:
            done = self.runner(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ServiceError(f"{self.kind}_command_failed") from exc
        if required and done.returncode != 0:
            raise ServiceError(f"{self.kind}_command_failed")
        return done


class LaunchdManager(_Manager):
    kind = "launchd"

    def __init__(self, *, home: Path, runner: Runner, uid: int, spawn: Spawn | None = None,
                 label: str = LAUNCHD_LABEL) -> None:
        self.sleep: Callable[[float], None] = time.sleep
        super().__init__(home=home, runner=runner)
        self.uid = uid
        self.spawn = spawn or default_spawn
        self.label = label

    @property
    def unit_path(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{self.label}.plist"

    def _desired(self, shim: Path, log_file: Path) -> bytes:
        # The PATH chosen at ``device enable`` stays (the service itself only sees launchd's PATH).
        try:
            current = plistlib.loads(self.unit_path.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            current = {}
        environment = current.get("EnvironmentVariables") if isinstance(current, dict) else None
        kept = environment.get("PATH") if isinstance(environment, dict) else None
        return launchd_plist(shim, log_file, path=kept if isinstance(kept, str) and kept else None, label=self.label)

    def install(self, shim: Path, log_file: Path) -> None:
        self.unit_path.parent.mkdir(parents=True, exist_ok=True)
        self.unit_path.write_bytes(launchd_plist(shim, log_file, label=self.label))
        launchd_reload(self._run, uid=self.uid, label=self.label, plist=self.unit_path, sleep=self.sleep)

    def reconcile(self, shim: Path, log_file: Path) -> bool:
        if not self.unit_path.exists():
            return False
        desired = self._desired(shim, log_file)
        if self.unit_path.read_bytes() == desired:
            return False
        self.unit_path.write_bytes(desired)
        return True

    def reload_detached(self) -> bool:
        """``bootout`` stops this service (SIGTERM, a clean stop) and ``bootstrap`` loads the new plist. The helper
        runs in its own session, so launchd's process-group kill on ``bootout`` does not reach it."""
        target = f"gui/{self.uid}"
        plist = _sh_quote(str(self.unit_path))
        script = (f"sleep {RELOAD_DELAY_SECONDS}; launchctl bootout {target}/{self.label}; "
                  f"i=0; while launchctl print {target}/{self.label} >/dev/null 2>&1 && [ $i -lt 20 ]; "
                  f"do sleep 0.25; i=$((i+1)); done; "
                  f"launchctl bootstrap {target} {plist} || {{ sleep 1; launchctl bootstrap {target} {plist}; }}")
        try:
            self.spawn(["/bin/sh", "-c", script])
        except OSError:
            return False
        return True

    def uninstall(self) -> None:
        self._run(["launchctl", "bootout", f"gui/{self.uid}/{self.label}"], required=False)
        self.unit_path.unlink(missing_ok=True)

    def status(self) -> ServiceStatus:
        listed = self._run(["launchctl", "print", f"gui/{self.uid}/{self.label}"], required=False)
        running = listed.returncode == 0 and "state = running" in (listed.stdout or "")
        return ServiceStatus(self.kind, self.unit_path.exists(), running)


class SystemdManager(_Manager):
    kind = "systemd"

    @property
    def unit_path(self) -> Path:
        return self.home / ".config" / "systemd" / "user" / SYSTEMD_UNIT

    def install(self, shim: Path, log_file: Path) -> None:  # noqa: ARG002 - journald keeps stdout; the log file too
        self.unit_path.parent.mkdir(parents=True, exist_ok=True)
        self.unit_path.write_text(systemd_unit(shim), encoding="utf-8")
        self._run(["systemctl", "--user", "daemon-reload"])
        self._run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT])

    def reconcile(self, shim: Path, log_file: Path) -> bool:  # noqa: ARG002 - see install
        if not self.unit_path.exists() or self.unit_path.read_text(encoding="utf-8") == systemd_unit(shim):
            return False
        self.unit_path.write_text(systemd_unit(shim), encoding="utf-8")
        self._run(["systemctl", "--user", "daemon-reload"], required=False)
        return True

    def uninstall(self) -> None:
        self._run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], required=False)
        self.unit_path.unlink(missing_ok=True)
        self._run(["systemctl", "--user", "daemon-reload"], required=False)

    def status(self) -> ServiceStatus:
        active = self._run(["systemctl", "--user", "is-active", SYSTEMD_UNIT], required=False)
        return ServiceStatus(self.kind, self.unit_path.exists(), (active.stdout or "").strip() == "active")


class WslTaskManager(_Manager):
    kind = "wsl-task"

    def __init__(self, *, home: Path, runner: Runner, distro: str) -> None:
        super().__init__(home=home, runner=runner)
        if not distro:
            raise ServiceError("wsl_distro_unknown")
        self.distro = distro

    def _powershell(self, script: str, *, required: bool = True) -> subprocess.CompletedProcess:
        return self._run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], required=required)

    def install(self, shim: Path, log_file: Path) -> None:  # noqa: ARG002 - the service writes its own log
        self._powershell(wsl_task_script(self.distro, shim))

    def uninstall(self) -> None:
        self._powershell(f"Unregister-ScheduledTask -TaskName {_ps_quote(WSL_TASK_NAME)} -Confirm:$false",
                         required=False)

    def status(self) -> ServiceStatus:
        done = self._powershell(f"(Get-ScheduledTask -TaskName {_ps_quote(WSL_TASK_NAME)}).State", required=False)
        state = (done.stdout or "").strip()
        return ServiceStatus(self.kind, done.returncode == 0 and bool(state), state == "Running")


def manager_for(os_name: str, *, home: Path | None = None, runner: Runner = default_runner, uid: int | None = None,
                distro: str = "") -> _Manager:
    base = home or Path.home()
    if os_name == OS_MACOS:
        return LaunchdManager(home=base, runner=runner, uid=os.getuid() if uid is None else uid,
                              label=instance_label(LAUNCHD_LABEL, home=base))
    if os_name == OS_LINUX:
        return SystemdManager(home=base, runner=runner)
    if os_name == OS_WSL2:
        return WslTaskManager(home=base, runner=runner, distro=distro)
    raise ServiceError("os_not_supported")


def launched_by_launchd(env: dict[str, str] | None = None) -> bool:
    """``True`` inside the LaunchAgent itself (launchd sets ``XPC_SERVICE_NAME`` to the job's label, which is
    :data:`LAUNCHD_LABEL` or, for a second installation, that label with its suffix, see :func:`instance_label`)."""
    name = (os.environ if env is None else env).get("XPC_SERVICE_NAME") or ""
    return name == LAUNCHD_LABEL or name.startswith(LAUNCHD_LABEL + ".")


__all__ = [
    "KIND_FOR_OS",
    "LaunchdManager",
    "ServiceError",
    "ServiceStatus",
    "SystemdManager",
    "WslTaskManager",
    "launched_by_launchd",
    "manager_for",
    "service_shim",
]
