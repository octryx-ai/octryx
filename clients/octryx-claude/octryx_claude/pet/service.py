"""The pet's autostart (``pet enable`` / ``disable`` / ``autostart``), always as the user, and its single-instance
lock."""

from __future__ import annotations

import contextlib
import os
import plistlib
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

from octryx_claude.device_service_units import launchd_reload

LAUNCHD_LABEL = "ai.octryx.claude.pet"
COMMAND_TIMEOUT = 30.0

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False)


class PetServiceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def launchd_plist(program: Sequence[str], log_file: Path, *, label: str = LAUNCHD_LABEL) -> bytes:
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [*program, "pet", "run"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    })


class LaunchAgent:
    def __init__(self, *, home: Path, uid: int, runner: Runner = default_runner, label: str = LAUNCHD_LABEL) -> None:
        self.home = home
        self.sleep: Callable[[float], None] = time.sleep
        self.uid = uid
        self.runner = runner
        self.label = label

    @property
    def path(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{self.label}.plist"

    def _run(self, argv: Sequence[str], *, required: bool) -> subprocess.CompletedProcess:
        try:
            done = self.runner(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PetServiceError("launchd_command_failed") from exc
        if required and done.returncode != 0:
            raise PetServiceError("launchd_command_failed")
        return done

    def install(self, program: Sequence[str], log_file: Path, *, restart: bool = True) -> bool:
        plist = launchd_plist(program, log_file, label=self.label)
        if not restart and self.path.exists() and self.path.read_bytes() == plist and self.running():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(plist)
        launchd_reload(self._run, uid=self.uid, label=self.label, plist=self.path, sleep=self.sleep)
        return True

    def remove(self) -> None:
        # The file first: when the pet turns itself off from its menu, the bootout ends this very process.
        self.path.unlink(missing_ok=True)
        self._run(["launchctl", "bootout", f"gui/{self.uid}/{self.label}"], required=False)

    def installed(self) -> bool:
        return self.path.exists()

    def running(self) -> bool:
        return self._run(["launchctl", "print", f"gui/{self.uid}/{self.label}"], required=False).returncode == 0


# --- Windows ---------------------------------------------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "OctryxPet"
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


class Registry(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class RunRegistry:
    def _key(self, access: int):  # noqa: ANN202
        import winreg  # noqa: PLC0415

        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)

    def get(self, name: str) -> str | None:
        import winreg  # noqa: PLC0415

        with self._key(winreg.KEY_READ) as key:
            try:
                return str(winreg.QueryValueEx(key, name)[0])
            except FileNotFoundError:
                return None

    def set(self, name: str, value: str) -> None:
        import winreg  # noqa: PLC0415

        with self._key(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg  # noqa: PLC0415

        with self._key(winreg.KEY_SET_VALUE) as key, contextlib.suppress(FileNotFoundError):
            winreg.DeleteValue(key, name)


def windowless_python(executable: str | None = None) -> Path:
    python = Path(executable or sys.executable)
    candidate = python.with_name("pythonw.exe")
    return candidate if candidate.exists() else python


def run_command(python: Path) -> list[str]:
    return [str(python), "-m", "octryx_claude.pet", "run"]


def default_spawn(argv: Sequence[str]) -> object:
    return subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True, creationflags=DETACHED if os.name == "nt" else 0)


class RunKey:
    def __init__(self, *, registry: Registry | None = None, spawn: Callable[[Sequence[str]], object] = default_spawn,
                 python: Path | None = None) -> None:
        self.registry = registry or RunRegistry()
        self.spawn = spawn
        self.python = python or windowless_python()

    def install(self) -> None:
        argv = run_command(self.python)
        try:
            self.registry.set(RUN_VALUE, subprocess.list2cmdline(argv))
        except OSError as exc:
            raise PetServiceError("registry_failed") from exc
        try:
            self.spawn(argv)  # now, not only at the next logon; a running pet makes this one exit (instance lock)
        except OSError as exc:
            raise PetServiceError("start_failed") from exc

    def remove(self) -> None:
        try:
            self.registry.delete(RUN_VALUE)
        except OSError as exc:
            raise PetServiceError("registry_failed") from exc

    def installed(self) -> bool:
        try:
            return self.registry.get(RUN_VALUE) is not None
        except OSError:
            return False


# --- one pet per user -----------------------------------------------------------------------------------------


@contextlib.contextmanager
def instance_lock(root: Path) -> Iterator[bool]:
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / "pet.lock", "a+b")  # noqa: SIM115 - held for the pet's lifetime
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            locked = False
        yield locked
    finally:
        handle.close()  # closing releases the lock on both systems


__all__ = ["LAUNCHD_LABEL", "RUN_VALUE", "LaunchAgent", "PetServiceError", "RunKey", "instance_lock", "launchd_plist",
           "run_command"]
