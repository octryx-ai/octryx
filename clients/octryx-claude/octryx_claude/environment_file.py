"""The repository's own environment file, read in the run's folder .

When the run's repository record points at an environment file (``coding_setup.environment_file``, e.g.
``coffee/web/claude/.octryx/environment.json``), the platform sends only that pointer: the preparation and the
pipeline (``pipeline``) read the file here, in the run's own branch, every time. Its format is exactly the record's
``coding_setup.environment`` (setup, test, system_test, lint, path, check, browser) and it is validated by the same
rules as the platform's (``backend/app/services/workflow_runs/workspace/spec.py``: ``validate_environment``,
``refused_command``; the backend's tests load this module and compare both on the same inputs). Stdlib only.

Everything is scoped to the **app folder**: the directory that contains ``.octryx/`` (else the file's directory).
The commands run there, ``path`` is relative to it; nothing outside it is read or run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

MAX_COMMANDS = 10
MAX_COMMAND_CHARS = 1000
MAX_FILE_BYTES = 64_000
BROWSERS = ("chrome", "chromium")
KEYS = {"setup", "test", "lint", "path", "check", "system_test", "browser", "serve"}
OK, MISSING, INVALID, SETUP_FAILED = "ok", "missing", "invalid", "setup_failed"
# The same pattern as the platform's ``spec._GLOBAL_INSTALL`` (and ``workspace_env._OUTSIDE``).
_GLOBAL_INSTALL = re.compile(
    r"(^|[\s;&|(])(sudo|doas|brew|apt|apt-get|yum|dnf|apk|port|choco|snap)\s|"
    r"\s(-g|--global|--user|--system)(\s|$)|\s--(prefix|target|root)[=\s]+(/|~|\$HOME)", re.IGNORECASE)


def refused_command(command: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return "an empty command"
    if len(text) > MAX_COMMAND_CHARS:
        return "longer than 1000 characters"
    if _GLOBAL_INSTALL.search(text):
        return "it installs outside the repository folder (sudo, a system package manager, a global or user install)"
    return None


def _strings(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in values if isinstance(item, str) and str(item).strip()][:MAX_COMMANDS]


def _relative_dirs(value: Any) -> list[str]:
    dirs = []
    for item in _strings(value):
        path = PurePosixPath(item)
        if not path.is_absolute() and ".." not in path.parts and item not in (".", ""):
            dirs.append(path.as_posix())
    return dirs


# The hands-on test (``hands_on``): how the built app is served, loopback only (``spec._serve`` on the platform).
SERVE_URL = re.compile(r"^http://(127\.0\.0\.1|localhost):\d{2,5}(/[^\s]*)?$")
MAX_READY_SECONDS = 900


def _serve(raw: Any, errors: list[str], warnings: list[str] | None = None) -> dict[str, Any] | None:
    if raw in (None, {}, ""):
        return None
    if not isinstance(raw, dict):
        errors.append("serve is an object with command, url, ready_seconds, parallel and persistent")
        return None
    if unknown := set(raw) - {"command", "url", "ready_seconds", "parallel", "persistent"}:
        if warnings is not None:
            warnings.append(f"unknown serve key ignored: {', '.join(sorted(unknown))} (a newer platform version?)")
    if "persistent" in raw and type(raw["persistent"]) is not bool:
        errors.append("serve.persistent is true or false (false: the app keeps no data across a restart)")
    if "parallel" in raw and type(raw["parallel"]) is not bool:
        errors.append("serve.parallel is true or false (false: the hands-on scenarios run one at a time)")
    command = " ".join(_strings(raw.get("command"))[:1])
    url = str(raw.get("url") or "").strip()
    ready = raw.get("ready_seconds", 180)
    if not command:
        errors.append("serve.command (how the app is started) is required")
    elif why := refused_command(command):
        errors.append(f"'{command[:80]}' is refused: {why}")
    if not SERVE_URL.match(url):
        errors.append("serve.url is a loopback address with its port, e.g. http://127.0.0.1:8080/")
    if type(ready) is not int or not 1 <= ready <= MAX_READY_SECONDS:
        errors.append(f"serve.ready_seconds is 1 to {MAX_READY_SECONDS}")
        ready = 180
    # parallel false: an app whose scenarios share a server's data runs them one at a time.
    return {"command": command, "url": url, "ready_seconds": ready,
            **({"parallel": False} if raw.get("parallel") is False else {}),
            # persistent false: the app keeps no data across a restart; scenarios seed in-session.
            **({"persistent": False} if raw.get("persistent") is False else {})}


def validate_environment(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """``(normalized, errors)``, the platform's rules (``spec.validate_environment``)."""
    if raw in (None, {}, ""):
        return None, []
    if not isinstance(raw, dict):
        return None, ["environment must be an object"]
    # ("defaults let the work run"): a key this platform does not know yet is a warning and
    # ignored, never a reason to refuse the file; only a known key with a wrong value is an error.
    unknown = set(raw) - KEYS
    errors: list[str] = []
    warnings = [f"unknown environment key ignored: {', '.join(sorted(unknown))} (a newer platform version?)"] \
        if unknown else []
    environment = {"setup": _strings(raw.get("setup")), "test": " ".join(_strings(raw.get("test"))[:1]),
                   "lint": " ".join(_strings(raw.get("lint"))[:1]), "path": _relative_dirs(raw.get("path")),
                   "check": _strings(raw.get("check")),
                   "system_test": " ".join(_strings(raw.get("system_test"))[:1])}
    browser = str(raw.get("browser") or "").strip().lower()
    if browser in BROWSERS:
        environment["browser"] = browser
    elif browser:
        errors.append(f"browser is one of: {', '.join(BROWSERS)}")
    if (serve := _serve(raw.get("serve"), errors, warnings)) is not None:
        environment["serve"] = serve
    if len(_strings(raw.get("path"))) != len(environment["path"]):
        errors.append("path entries are directories inside the repository folder (relative, no '..')")
    for command in [*environment["setup"], *environment["check"], environment["test"], environment["lint"],
                    environment["system_test"]]:
        if command and (why := refused_command(command)):
            errors.append(f"'{command[:80]}' is refused: {why}")
    if not environment["test"]:
        errors.append("environment.test (the test command) is required")
    if warnings:
        environment["warnings"] = warnings  # shown in the run (environment_file_warning), never blocking
    return environment, errors


def app_folder(environment_file: str) -> str:
    parent = PurePosixPath(environment_file).parent
    folder = parent.parent if parent.name == ".octryx" else parent
    return folder.as_posix() or "."


def _pointer_error(environment_file: str) -> str | None:
    path = PurePosixPath(environment_file)
    if (not environment_file or len(environment_file) > 200 or path.is_absolute() or ".." in path.parts
            or "\\" in environment_file or not environment_file.endswith(".json") or path.name == ".json"):
        return "the environment file is not a repository-relative .json path"
    return None


def resolve(root: Path, environment_file: str, pin: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run's environment file: its pinned content when the platform sent one for this file
    (the file is the run's contract, pinned at its first valid read; a file the agent rewrote in the
    working tree is never what the run executes), else the file in ``root``."""
    file = str(environment_file or "")
    pinned = pin if isinstance(pin, dict) and pin.get("file") == file and isinstance(pin.get("environment"), dict) \
        else None
    if pinned is None:
        return read(root, file)
    environment, errors = validate_environment(pinned["environment"])
    found: dict[str, Any] = {"file": file, "app_folder": app_folder(file), "errors": [], "pinned": True,
                             "sha256": str(pinned.get("sha256") or "")}
    if environment is None or errors:
        return {**found, "state": INVALID, "errors": errors or ["the pinned environment is empty"]}
    commands = [command for command in (environment["test"], environment["system_test"]) if command]
    return {**found, "state": OK, "environment": environment, "commands": commands}


def read(root: Path, environment_file: str) -> dict[str, Any]:
    """``{file, app_folder, state, errors, environment, sha256, commands}`` of the file in ``root``."""
    file = str(environment_file or "")
    found: dict[str, Any] = {"file": file, "app_folder": app_folder(file), "errors": []}
    if problem := _pointer_error(file):
        return {**found, "state": INVALID, "errors": [problem]}
    base = Path(os.path.realpath(root))
    target = Path(os.path.realpath(base / file))
    if not target.is_relative_to(base):
        return {**found, "state": INVALID, "errors": ["the file resolves outside the repository folder"]}
    if not target.is_file():
        return {**found, "state": MISSING}
    data = target.read_bytes()
    found["sha256"] = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_FILE_BYTES:
        return {**found, "state": INVALID, "errors": ["the file is larger than 64 KB"]}
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        return {**found, "state": INVALID, "errors": [f"not valid JSON: {error}"[:300]]}
    environment, errors = validate_environment(raw)
    if environment is None and not errors:
        errors = ["environment.test (the test command) is required"]
    if errors:
        return {**found, "state": INVALID, "errors": errors}
    commands = [command for command in (environment["test"], environment["system_test"]) if command]
    return {**found, "state": OK, "environment": environment, "commands": commands}


def folder_of(root: Path, account: dict[str, Any]) -> Path:
    """The app folder inside ``root`` (it exists: the file is in it)."""
    return Path(os.path.realpath(root)) / str(account.get("app_folder") or ".")


def exclude(root: Path, account: dict[str, Any]) -> None:
    """The app folder's environment (its ``path`` tops, ``.venv``), test reports and caches never enter the change
    or the pipeline's tree: local excludes (``.git/info/exclude``), never a commit."""
    folder = str(account.get("app_folder") or ".")
    if folder == ".":
        return  # the repository root: ``work_git.RUNTIME_EXCLUDES`` and the preparation cover it
    tops = {PurePosixPath(item).parts[0] for item in dict(account.get("environment") or {}).get("path") or []}
    names = sorted({".venv", "test-reports", ".pytest_cache", *(top for top in tops if top not in (".", ".."))})
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
                              capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return
    if done.returncode != 0:
        return
    target = Path(root) / done.stdout.strip()
    lines = target.read_text().splitlines() if target.is_file() else []
    missing = [pattern for pattern in (f"/{folder}/{name}/" for name in names) if pattern not in lines]
    if missing:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join([*lines, *missing]) + "\n")


def setup(folder: Path, environment: dict[str, Any], env: dict[str, str]) -> tuple[bool, list[dict[str, Any]]]:
    """Make the app folder ready: nothing when every ``check`` passes, else the ``setup`` commands in order (a
    failing one stops). Without ``check`` the setup runs every time (it is expected to be idempotent). The checks and
    the setup run exactly like a declaration on the record (``workspace_env._probe`` / ``_run``)."""
    from . import browser, workspace_env  # noqa: PLC0415

    checks = list(environment.get("check") or [])
    if checks and all(workspace_env._probe(folder, {"what": command, "shell": command}, env)["ok"]
                      for command in checks):
        return True, []
    log: list[dict[str, Any]] = []
    for command in environment.get("setup") or []:
        if browser.skips_setup(command, env):
            log.append({"command": command, "exit_code": 0, "seconds": 0,
                        "output_tail": "skipped: the tests use this device's Google Chrome (browser.py)"})
            continue
        if why := refused_command(command):  # validated when read; checked again right before it runs
            log.append({"command": command, "exit_code": None, "seconds": 0, "output_tail": f"refused: {why}"})
            return False, log
        started = time.monotonic()
        code, output = workspace_env._run(["/bin/sh", "-c", command], folder, env, workspace_env.SETUP_TIMEOUT)
        log.append({"command": command, "exit_code": code, "seconds": round(time.monotonic() - started, 1),
                    "output_tail": output})
        if code != 0:
            return False, log
    return True, log


__all__ = ["INVALID", "MISSING", "OK", "SETUP_FAILED", "app_folder", "exclude", "folder_of", "read", "refused_command",
           "setup", "validate_environment"]
