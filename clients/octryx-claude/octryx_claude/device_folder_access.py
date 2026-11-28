"""Real folder access from the device service's own process: macOS privacy (TCC) can block a LaunchAgent
where a terminal is allowed, and the background service cannot answer the prompt."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from . import device_state
from .state import LocalState, read_json, write_private_json

REASON_NOT_ACCESSIBLE = "device_folder_not_accessible"
PROBE_FILE = "device-folder-probe.json"
WATCH_SECONDS = 2.0
REFRESH_SECONDS = 60.0
PROBE_WAIT_SECONDS = 20.0
ALIVE_SECONDS = 150.0
_BLOCKED = frozenset({errno.EPERM, errno.EACCES})


def service_python() -> str:
    return os.path.realpath(sys.executable)


def access_problem(folder: str) -> str:
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                entry.stat(follow_symlinks=False)
                break
    except PermissionError:
        return REASON_NOT_ACCESSIBLE
    except OSError as exc:
        return REASON_NOT_ACCESSIBLE if exc.errno in _BLOCKED else ""
    return ""


def access_hint(folder: str, *, os_name: str, python: str = "") -> str:
    if os_name == device_state.OS_MACOS:
        return (f"macOS blocks the background service from {folder}; allow it under System Settings → Privacy & "
                f"Security → Full Disk Access (or Files and Folders) for {python or service_python()}, "
                "or use a folder in your home.")
    return f"the background service cannot read {folder}; check its permissions or use a folder in your home."


# --- probes answered by the running service ---------------------------------------------------------------------


def request_probe(state: LocalState, folders: list[str]) -> str:
    request_id = uuid.uuid4().hex
    write_private_json(state.root / PROBE_FILE, {"id": request_id, "folders": list(folders)})
    return request_id


def answer_probe(state: LocalState, *, now: Callable[[], float] = time.time) -> bool:
    path = state.root / PROBE_FILE
    request = read_json(path)
    request_id = str(request.get("id") or "")
    if not request_id:
        return False
    folders = [str(item) for item in request.get("folders") or [] if isinstance(item, str)]
    results = {folder: access_problem(folder) for folder in folders}
    status = device_state.read_status(state)
    status["folder_probe"] = {"id": request_id, "results": results, "at": now()}
    status["service_python"] = service_python()
    device_state.write_status(state, status)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    return True


def refresh_folder_access(state: LocalState, *, now: Callable[[], float] = time.time) -> None:
    folders = list(device_state.load_device(state).get("folders") or [])
    status = device_state.read_status(state)
    status["folder_access"] = {folder: access_problem(folder) for folder in folders}
    status["folder_access_at"] = now()
    status["service_python"] = service_python()
    device_state.write_status(state, status)


def service_alive(state: LocalState, *, now: Callable[[], float] = time.time) -> bool:
    at = device_state.read_status(state).get("folder_access_at")
    return isinstance(at, (int, float)) and now() - at <= ALIVE_SECONDS


async def await_probe(state: LocalState, request_id: str, *, timeout: float = PROBE_WAIT_SECONDS,
                      sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> dict[str, str] | None:
    waited = 0.0
    while waited <= timeout:
        probe = device_state.read_status(state).get("folder_probe")
        if isinstance(probe, dict) and probe.get("id") == request_id and isinstance(probe.get("results"), dict):
            return {str(key): str(value or "") for key, value in probe["results"].items()}
        await sleep(0.5)
        waited += 0.5
    return None


def probe_from_service(state: LocalState, folders: list[str], *, timeout: float = PROBE_WAIT_SECONDS,
                       sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> dict[str, str] | None:
    request_id = request_probe(state, folders)
    answer = asyncio.run(await_probe(state, request_id, timeout=timeout, sleep=sleep))
    if answer is None:
        with contextlib.suppress(FileNotFoundError):
            (state.root / PROBE_FILE).unlink()
    return answer


async def folder_watch(state: LocalState, stop: asyncio.Event, *, interval: float = WATCH_SECONDS,
                       refresh: float = REFRESH_SECONDS) -> None:
    last_refresh = -refresh
    elapsed = 0.0
    while not stop.is_set():
        with contextlib.suppress(OSError, ValueError):
            answer_probe(state)
            if elapsed - last_refresh >= refresh:
                last_refresh = elapsed
                refresh_folder_access(state)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), interval)
        elapsed += interval


def blocked(results: dict[str, Any]) -> list[str]:
    return [folder for folder, code in results.items() if code == REASON_NOT_ACCESSIBLE]


__all__ = [
    "REASON_NOT_ACCESSIBLE",
    "access_hint",
    "access_problem",
    "answer_probe",
    "await_probe",
    "blocked",
    "folder_watch",
    "probe_from_service",
    "refresh_folder_access",
    "request_probe",
    "service_alive",
    "service_python",
]
