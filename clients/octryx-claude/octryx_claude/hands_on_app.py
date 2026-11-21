"""The app of a hands-on pass (``hands_on``): its serve group, the serve URL's lock on this device, and the
groups a previous instance of the launcher left running.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SERVE_LOG_TAIL = 3000


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - a loopback URL the file validated
            return response.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


# One app per serve URL on this device: two runs testing at the same time with the same "serve" would fight over
# the port, and an app that already answers would be the other run's. A pass waits for the URL's lock and refuses
# to test an app it did not start.
LOCK_WAIT_SECONDS = 1800


def _step(name: str, since: float, **facts: Any) -> None:
    """One step of a hands-on pass in the device log, with its seconds, so a slow or silent pass shows which step
    (setup, the URL's lock, the app's start, the browser, the base recheck) takes the time."""
    import logging  # noqa: PLC0415

    logging.getLogger(__name__).info("hands-on: %s after %.0f s%s", name, time.monotonic() - since,
                                     "".join(f", {key}={value}" for key, value in facts.items()))


@contextlib.contextmanager
def url_lock(url: str, wait_seconds: float = LOCK_WAIT_SECONDS) -> Iterator[bool]:
    """Hold this device's lock for ``url`` (``True``), or ``False`` when another pass held it too long."""
    import fcntl  # noqa: PLC0415 - POSIX: the device runs on macOS / Linux (WSL2)

    parsed = urllib.parse.urlsplit(url)
    name = f"octryx-hands-on-{parsed.hostname or 'local'}-{parsed.port or 80}.lock"
    with open(Path(tempfile.gettempdir()) / name, "a+") as handle:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(2)
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _serve_file(url: str) -> Path:
    parsed = urllib.parse.urlsplit(url)
    return Path(tempfile.gettempdir()) / f"octryx-hands-on-{parsed.hostname or 'local'}-{parsed.port or 80}.serve.json"


def _started(pid: int) -> str:
    """The process's start time as ``ps`` shows it (``""``: gone); unchanged by an exec, so it names the process."""
    try:
        done = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                              check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip()


def _owner(root: Path | None = None) -> str:
    """The launcher a serve group belongs to: its state folder. Two launchers on one Mac (a test stack's next to the
    person's own, or two test workers) share the temp folder; one never ends the other's running app (
    a starting device service ended a running hands-on test's http.server, S2 got ERR_CONNECTION_REFUSED)."""
    from .tools import default_root  # noqa: PLC0415

    return str((root or default_root()).resolve())


def reap_orphan(url: str) -> bool:
    """End this device's own serve group a stopped launcher left on ``url`` (a launcher restart
    left 's `python3 -m http.server 8090` running; every later hands-on run refused "something else already
    answers"). Only the group the file names, only this launcher's, and only while its leader is the same process
    (its start time)."""
    return _reap_record(_serve_file(url), _owner())


def _reap_record(record: Path, owner: str) -> bool:
    import json  # noqa: PLC0415

    try:
        data = json.loads(record.read_text())
    except (OSError, ValueError):
        record.unlink(missing_ok=True)  # unreadable: nobody's record
        return False
    if data.get("owner") != owner:
        return False  # another launcher's app (or one recorded before owners): never ours to end
    record.unlink(missing_ok=True)
    pgid, started = int(data.get("pgid") or 0), str(data.get("started") or "")
    if pgid <= 1 or not started or _started(pgid) != started:
        return False
    import logging  # noqa: PLC0415

    logging.getLogger(__name__).warning("reaping the serve group %s (%s) recorded in %s", pgid,
                                        str(data.get("command") or "")[:200], record.name)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except OSError:
            return True
        for _ in range(10):
            if not _started(pgid):
                return True
            time.sleep(0.5)
    return True


def reap_all(root: Path | None = None) -> int:
    """At the device service's start: end every serve group a previous instance of this launcher (``root``, its
    state folder) recorded and left running (a launcher restart would otherwise leave a hands-on run's server
    behind, adopted by PID 1). Each group only while its leader is still the recorded process; another
    launcher's groups stay. The number of groups ended."""
    owner = _owner(root)
    return sum(1 for record in Path(tempfile.gettempdir()).glob("octryx-hands-on-*.serve.json")
               if _reap_record(record, owner))


# The hands-on report's ``code`` (the platform judges codes, never texts):
# which part of the environment or the work stopped the pass. The platform's catalog
# (``workflow_runs/failure_codes.json``) says who caused it and whether a retry can help.
ENV_FILE_INVALID, SERVE_MISSING, ENV_SETUP_FAILED = "env_file_invalid", "serve_missing", "env_setup_failed"
DEVICE_BUSY, PORT_IN_USE, BROWSER_UNAVAILABLE = "device_busy", "port_in_use", "browser_unavailable"
APP_EXITED, APP_KILLED, APP_NOT_ANSWERING = "app_exited", "app_killed", "app_not_answering"
APP_STATES = {APP_EXITED: "exited", APP_KILLED: "was killed", APP_NOT_ANSWERING: "did not answer"}


def start_app(serve: dict[str, Any], folder: Path, env: dict[str, str], log: Path) -> tuple[Any, str]:
    """``(process, problem)``: the app's serve command running and answering on its URL, or why not."""
    import json  # noqa: PLC0415

    with log.open("wb") as out:
        process = subprocess.Popen(serve["command"], shell=True, cwd=folder, env=env, stdout=out,  # noqa: S602
                                   stderr=subprocess.STDOUT, start_new_session=True)
    process.octryx_started = time.monotonic()  # for serve_end's duration
    process.octryx_log = log
    try:  # the group is ours: a later pass may end it when this launcher stops before it does
        _serve_file(serve["url"]).write_text(json.dumps({"pgid": process.pid, "command": serve["command"],
                                                         "started": _started(process.pid), "url": serve["url"],
                                                         "owner": _owner()}))
    except OSError:
        pass
    deadline = time.monotonic() + int(serve.get("ready_seconds") or 180)
    while time.monotonic() < deadline:
        if _answers(serve["url"]):
            return process, ""
        if process.poll() is not None:
            break
        time.sleep(1)
    LAST_END.update(stop_app(process, serve["url"], by="start_app"))
    tail = log.read_bytes()[-SERVE_LOG_TAIL:].decode("utf-8", "replace") if log.exists() else ""
    code = process.poll()
    state = (APP_STATES[APP_KILLED] if code is not None and code < 0 else APP_STATES[APP_EXITED] if code is not None
             else APP_STATES[APP_NOT_ANSWERING])
    return None, f"the app ({serve['command']}) {state} on {serve['url']}:\n{tail}"


def app_problem_code(problem: str) -> str:
    """The code of :func:`start_app`'s problem (its own state words)."""
    return next((code for code, words in APP_STATES.items() if f") {words} on " in problem), APP_NOT_ANSWERING)


# How the last serve group of this process ended (``serve_end`` in the hands-on report): its exit code or signal,
# who ended it and after how long (a nightly run once ended on an unexplained SIGTERM).
LAST_END: dict[str, Any] = {}


def stop_app(process: Any, url: str = "", *, by: str = "stop_app") -> dict[str, Any]:
    """End the serve group (TERM, KILL after 15 s); how it ended, also written to its serve log."""
    if url:
        _serve_file(url).unlink(missing_ok=True)
    if process is None:
        return {}
    ended_before = process.poll() is not None
    if not ended_before:
        try:
            os.killpg(process.pid, signal.SIGTERM)  # the serve command's own process group only
            process.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
    code = process.poll()
    end = {"by": "itself" if ended_before else by, "exit_code": code if code is None or code >= 0 else None,
           "signal": -code if isinstance(code, int) and code < 0 else None,
           "seconds": round(time.monotonic() - float(getattr(process, "octryx_started", time.monotonic())), 1)}
    log = getattr(process, "octryx_log", None)
    if isinstance(log, Path):
        with contextlib.suppress(OSError), log.open("a", encoding="utf-8") as out:
            out.write(f"\n[octryx] serve group ended: {end}\n")
    return end
